'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { getApiUrl, getWsUrl } from '@/lib/config';
import { apiJson } from '@/lib/fetchWithRetry';
import {
  CreateResponse,
  NewsletterCreateRequest,
  StageContent,
  TaskState,
} from '@/types/newsletter';
import { WsEvent } from '@/types/websocket-events';

export interface ConsoleLine {
  text: string;
  stage_num: number;
  ts: number;
}

export type NewsletterTaskState = {
  taskId: string | null;
  task: TaskState | null;
  stageContent: Record<number, StageContent | null>;
  console: ConsoleLine[];
  loading: boolean;
  error: string | null;
};

const initial: NewsletterTaskState = {
  taskId: null,
  task: null,
  stageContent: {},
  console: [],
  loading: false,
  error: null,
};

// REST poll cadences mirror MARS-PaperPulse: console at 1s for snappy streaming,
// task-state at 5s because it only changes on stage transitions. WebSocket only
// carries the (low-rate) completion / failure events — console lines arrive via
// REST so we never lose them across reconnects.
const CONSOLE_POLL_MS = 1000;
const STATUS_POLL_MS = 5000;

interface ConsolePollResponse {
  lines: string[];
  next_index: number;
  stage_num: number;
  status: string;
  is_done: boolean;
  error: string | null;
}

export function useNewsletterTask() {
  const [state, setState] = useState<NewsletterTaskState>(initial);

  // All stream sources share these refs so cleanup is centralised: closing the
  // WS and stopping both polls in one place avoids dangling intervals when the
  // user re-runs a stage or unmounts mid-stream.
  const wsRef = useRef<WebSocket | null>(null);
  const wsStageRef = useRef<number | null>(null);
  const consolePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const statusPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const consoleIndexRef = useRef(0);
  const consoleStageRef = useRef<number | null>(null);

  const setError = useCallback((err: unknown) => {
    setState((s) => ({ ...s, error: err instanceof Error ? err.message : String(err), loading: false }));
  }, []);

  const refreshTask = useCallback(async (taskId: string) => {
    try {
      const task = await apiJson<TaskState>(`/api/newsletter/${taskId}`);
      setState((s) => ({ ...s, task }));
      return task;
    } catch (err) {
      setError(err);
      return null;
    }
  }, [setError]);

  const fetchStageContent = useCallback(async (taskId: string, stageNum: number) => {
    try {
      const content = await apiJson<StageContent>(`/api/newsletter/${taskId}/stages/${stageNum}/content`);
      setState((s) => ({ ...s, stageContent: { ...s.stageContent, [stageNum]: content } }));
      return content;
    } catch (err) {
      setError(err);
      return null;
    }
  }, [setError]);

  // ── Stream lifecycle ──────────────────────────────────────────────────────

  const stopConsolePoll = useCallback(() => {
    if (consolePollRef.current) {
      clearInterval(consolePollRef.current);
      consolePollRef.current = null;
    }
  }, []);

  const stopStatusPoll = useCallback(() => {
    if (statusPollRef.current) {
      clearInterval(statusPollRef.current);
      statusPollRef.current = null;
    }
  }, []);

  const closeWs = useCallback(() => {
    if (wsRef.current) {
      try { wsRef.current.close(); } catch { /* noop */ }
      wsRef.current = null;
      wsStageRef.current = null;
    }
  }, []);

  // Fully stop streaming for the current stage (poll + WS). Use this when the
  // stage finishes, the user resumes a different task, or the component unmounts.
  const stopStreams = useCallback(() => {
    stopConsolePoll();
    stopStatusPoll();
    closeWs();
  }, [stopConsolePoll, stopStatusPoll, closeWs]);

  // Drain the in-memory console buffer for ``stageNum`` since the last index.
  // Tagged with ``stage_num`` so the UI can filter when a previous stage's
  // tail arrives just as a new stage starts streaming.
  const startConsolePoll = useCallback((taskId: string, stageNum: number) => {
    stopConsolePoll();
    consoleIndexRef.current = 0;
    consoleStageRef.current = stageNum;

    const tick = async () => {
      try {
        const url = getApiUrl(
          `/api/newsletter/${taskId}/stages/${stageNum}/console?since=${consoleIndexRef.current}`,
        );
        const resp = await fetch(url);
        if (!resp.ok) return;
        const data = (await resp.json()) as ConsolePollResponse;

        if (data.lines && data.lines.length > 0) {
          const now = Date.now();
          const newLines: ConsoleLine[] = data.lines.map((text) => ({
            text, stage_num: stageNum, ts: now,
          }));
          setState((s) => ({ ...s, console: [...s.console, ...newLines] }));
          consoleIndexRef.current = data.next_index;
        }

        // Stop polling once the backend reports the stage is no longer running.
        // The WS still owns the user-visible completion event; here we just
        // tear down the interval so we don't keep hitting the endpoint.
        if (data.is_done) {
          stopConsolePoll();
        }
      } catch {
        // Transient network errors are expected; keep polling — they recover on the next tick.
      }
    };

    void tick();
    consolePollRef.current = setInterval(tick, CONSOLE_POLL_MS);
  }, [stopConsolePoll]);

  // Periodically refresh task state so the stepper / progress bar stay in sync
  // even if a WS event is missed. Stops itself when the stage is done.
  const startStatusPoll = useCallback((taskId: string, stageNum: number) => {
    stopStatusPoll();

    const tick = async () => {
      const task = await refreshTask(taskId);
      if (!task) return;
      const stage = task.stages.find((s) => s.stage_number === stageNum);
      if (!stage) return;
      if (stage.status === 'completed' || stage.status === 'failed') {
        stopStatusPoll();
        // One last content fetch so the UI displays the rendered markdown
        // even when the WS is unavailable (proxies, restart, etc.).
        void fetchStageContent(taskId, stageNum);
      }
    };

    statusPollRef.current = setInterval(tick, STATUS_POLL_MS);
  }, [refreshTask, fetchStageContent, stopStatusPoll]);

  const openWs = useCallback((taskId: string, stageNum: number) => {
    closeWs();
    const url = getWsUrl(`/ws/newsletter/${taskId}/${stageNum}`);
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      // WS unavailable (e.g. behind a proxy that strips upgrade headers) — the
      // REST polls already provide the same data, so we just return silently.
      return;
    }
    wsRef.current = ws;
    wsStageRef.current = stageNum;

    ws.onmessage = (ev) => {
      try {
        const msg: WsEvent = JSON.parse(ev.data);
        // Console lines come via REST poll to avoid duplication.
        if (msg.event_type === 'stage_completed' || msg.event_type === 'stage_failed') {
          void refreshTask(taskId);
          void fetchStageContent(taskId, stageNum);
          stopStreams();
        }
      } catch {
        /* ignore parse errors — REST keeps us correct */
      }
    };

    ws.onerror = () => {
      // No fallback to surface — REST polls are already running.
    };

    ws.onclose = () => {
      // Trigger one more refresh in case the WS shut down right as the stage finished.
      void refreshTask(taskId);
    };
  }, [closeWs, refreshTask, fetchStageContent, stopStreams]);

  // ── Public actions ────────────────────────────────────────────────────────

  const resume = useCallback(async (taskId: string) => {
    stopStreams();
    setState((s) => ({ ...s, loading: true, error: null, console: [], taskId, stageContent: {} }));
    try {
      const task = await apiJson<TaskState>(`/api/newsletter/${taskId}`);
      setState((s) => ({ ...s, task, loading: false }));

      // Prefetch content for any completed stage so the stepper renders instantly.
      for (const stage of task.stages) {
        if (stage.status === 'completed') {
          try {
            const content = await apiJson<StageContent>(`/api/newsletter/${taskId}/stages/${stage.stage_number}/content`);
            setState((s) => ({ ...s, stageContent: { ...s.stageContent, [stage.stage_number]: content } }));
          } catch {
            // Best-effort prefetch — a single 4xx/5xx must not abort resume.
          }
        }
      }

      // If a stage was running when the user left, reattach all streams.
      const running = task.stages.find((s) => s.status === 'running');
      if (running) {
        startConsolePoll(taskId, running.stage_number);
        startStatusPoll(taskId, running.stage_number);
        openWs(taskId, running.stage_number);
      }
    } catch (err) {
      setError(err);
    }
  }, [setError, stopStreams, startConsolePoll, startStatusPoll, openWs]);

  const reset = useCallback(() => {
    stopStreams();
    setState(initial);
  }, [stopStreams]);

  const create = useCallback(async (req: NewsletterCreateRequest) => {
    setState((s) => ({ ...s, loading: true, error: null, console: [] }));
    try {
      const res = await apiJson<CreateResponse>('/api/newsletter/create', {
        method: 'POST',
        body: JSON.stringify(req),
      });
      setState((s) => ({ ...s, taskId: res.task_id, loading: false }));
      await refreshTask(res.task_id);
      await fetchStageContent(res.task_id, 1);
      return res.task_id;
    } catch (err) {
      setError(err);
      return null;
    }
  }, [refreshTask, fetchStageContent, setError]);

  const executeStage = useCallback(async (
    taskId: string,
    stageNum: number,
    overrides?: { mode_override?: string; config_overrides?: Record<string, unknown> },
  ) => {
    // Stop any prior streams first — re-runs must not blend logs across runs.
    stopStreams();
    setState((s) => ({ ...s, loading: true, error: null, console: [] }));
    try {
      await apiJson(`/api/newsletter/${taskId}/stages/${stageNum}/execute`, {
        method: 'POST',
        body: JSON.stringify(overrides || {}),
      });
      // Refresh once before opening streams so the UI shows status="running"
      // immediately rather than relying on the next 5s poll tick.
      await refreshTask(taskId);

      startConsolePoll(taskId, stageNum);
      startStatusPoll(taskId, stageNum);
      openWs(taskId, stageNum);

      setState((s) => ({ ...s, loading: false }));
    } catch (err) {
      setError(err);
    }
  }, [stopStreams, refreshTask, startConsolePoll, startStatusPoll, openWs, setError]);

  const updateStageContent = useCallback(async (taskId: string, stageNum: number, content: string) => {
    try {
      await apiJson(`/api/newsletter/${taskId}/stages/${stageNum}/content`, {
        method: 'PUT',
        body: JSON.stringify({ content, field: 'default' }),
      });
      await refreshTask(taskId);
      await fetchStageContent(taskId, stageNum);
    } catch (err) {
      setError(err);
    }
  }, [refreshTask, fetchStageContent, setError]);

  const refineStage = useCallback(async (taskId: string, stageNum: number, message: string, content: string) => {
    try {
      const res = await apiJson<{ refined_content: string }>(`/api/newsletter/${taskId}/stages/${stageNum}/refine`, {
        method: 'POST',
        body: JSON.stringify({ message, content }),
      });
      return res.refined_content;
    } catch (err) {
      setError(err);
      return null;
    }
  }, [setError]);

  const regeneratePdf = useCallback(async (taskId: string) => {
    try {
      return await apiJson<{ success: boolean; pdf_path?: string; backend_used?: string; error?: string }>(
        `/api/newsletter/${taskId}/regenerate-pdf`,
        { method: 'POST', body: JSON.stringify({}) },
      );
    } catch (err) {
      setError(err);
      return null;
    }
  }, [setError]);

  useEffect(() => () => stopStreams(), [stopStreams]);

  return {
    ...state,
    create,
    resume,
    reset,
    refreshTask,
    fetchStageContent,
    executeStage,
    updateStageContent,
    refineStage,
    regeneratePdf,
    openWs,
    closeWs,
  };
}
