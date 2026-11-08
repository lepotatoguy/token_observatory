export interface ForecastProvider {
  daily: number | null;
  share: number | null;
  start_of_day_capacity: number | null;
  remaining_capacity: number | null;
  used_today: number | null;
  demand_method: "flat" | "weekday_regression";
  calibration: "history" | null;
  calibration_pairs: number;
  shrinkage: number;
  backtest: { model_mae: number; baseline_mae: number; days: number } | null;
  calibration_kind: "single" | "by_type" | null;
  calibration_readings: number;
  rolling: { mae_points: number; single_mae_points: number; readings: number } | null;
  budget_check: { within: number; scored: number } | null;
  confidence: "low" | "medium" | "normal";
  days_used: number;
  estimated: boolean;
  excluded: "no_weekly_quota" | "insufficient_data" | null;
  warnings: string[];
}
export interface Forecast {
  date: string;
  generated_at: number | null;
  total: number;
  warnings: string[];
  providers: Record<string, ForecastProvider>;
}
