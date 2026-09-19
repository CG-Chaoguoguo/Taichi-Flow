/// <reference types="vite/client" />

interface Window {
  taichiFlowDesktop?: {
    runtime?: string;
    mode?: string;
    apiUrl?: string;
    version?: string;
    buildId?: string;
    distributionMode?: string;
    apiContractVersion?: number;
    selectDirectory?: (options?: { defaultPath?: string }) => Promise<{ canceled: boolean; path: string | null }>;
  };
}
