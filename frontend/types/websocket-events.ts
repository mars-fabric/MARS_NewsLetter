export type WsEventType = 'status' | 'console_output' | 'stage_completed' | 'stage_failed';

export interface WsEvent<T = Record<string, unknown>> {
  event_type: WsEventType;
  timestamp: string;
  data: T;
  run_id?: string;
  session_id?: string;
}

export interface ConsoleOutputEvent {
  text: string;
  stage_num: number;
}

export interface StageCompletedEvent {
  stage_num: number;
  stage_name: string;
}

export interface StageFailedEvent {
  stage_num: number;
  error: string;
}
