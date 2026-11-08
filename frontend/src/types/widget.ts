export interface WidgetStatus {
  enabled: boolean;
  available: boolean;
  reason: string | null;
  running: boolean;
  starting: boolean;
  error: string | null;
}
