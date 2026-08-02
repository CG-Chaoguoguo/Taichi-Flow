/// <reference types="vite/client" />

interface Window {
  taichiFlowDesktop?: {
    runtime?: string;
    mode?: string;
    apiUrl?: string;
    selectDirectory?: (options?: { defaultPath?: string }) => Promise<{ canceled: boolean; path: string | null }>;
  };
}
