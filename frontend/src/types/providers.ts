export interface LocalProvider {
  listen: number;
  target: number;
  server_up?: boolean;
  listening?: boolean;
  chat_files?: number;
  error?: string;
}
export interface ProviderStatus {
  enabled: string[];
  settings: ProviderSettings;
  names: Record<string, string>;
  detected: Record<string, string | boolean | null>;
  cloud: string[];
  local: Record<string, LocalProvider>;
  minimax?: { configured: boolean; region: string };
}
export interface ProviderSettings {
  setup_done: boolean;
  enabled: Record<string, boolean>;
  ports: Record<string, { listen: number; target: number }>;
}
export interface ProviderChoice {
  enabled: Record<string, boolean>;
  ports: Record<string, { listen: number; target: number }>;
  setup_done: boolean;
}
