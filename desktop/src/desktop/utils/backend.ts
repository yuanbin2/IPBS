export interface BackendStatus {
  connected: boolean
  url: string
  latency?: number
}

export interface BackendConfig {
  host: string
  port: number
  protocol: 'http' | 'https'
}

export class BackendManager {
  private config: BackendConfig
  private statusCheckInterval: ReturnType<typeof setInterval> | null = null
  private listeners: Array<(status: BackendStatus) => void> = []

  constructor(config?: Partial<BackendConfig>) {
    this.config = {
      host: config?.host || '127.0.0.1',
      port: config?.port || 8000,
      protocol: config?.protocol || 'http'
    }
  }

  get url(): string {
    return `${this.config.protocol}://${this.config.host}:${this.config.port}`
  }

  async checkStatus(): Promise<BackendStatus> {
    const startTime = Date.now()

    try {
      const response = await fetch(`${this.url}/api/health/`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000)
      })

      const latency = Date.now() - startTime

      return {
        connected: response.ok,
        url: this.url,
        latency
      }
    } catch {
      return {
        connected: false,
        url: this.url
      }
    }
  }

  startStatusCheck(intervalMs: number = 30000): void {
    this.stopStatusCheck()

    // Initial check
    this.checkAndNotify()

    // Periodic checks
    this.statusCheckInterval = setInterval(() => {
      this.checkAndNotify()
    }, intervalMs)
  }

  stopStatusCheck(): void {
    if (this.statusCheckInterval) {
      clearInterval(this.statusCheckInterval)
      this.statusCheckInterval = null
    }
  }

  onStatusChange(listener: (status: BackendStatus) => void): () => void {
    this.listeners.push(listener)

    // Return unsubscribe function
    return () => {
      const index = this.listeners.indexOf(listener)
      if (index > -1) {
        this.listeners.splice(index, 1)
      }
    }
  }

  private async checkAndNotify(): Promise<void> {
    const status = await this.checkStatus()
    this.listeners.forEach(listener => listener(status))
  }

  updateConfig(config: Partial<BackendConfig>): void {
    this.config = { ...this.config, ...config }
  }
}

// Singleton instance
export const backendManager = new BackendManager()

// Helper function to get API base URL
export function getApiBaseUrl(): string {
  return backendManager.url
}

// Helper function for API calls with retry
export async function apiCall<T>(
  endpoint: string,
  options: RequestInit = {},
  retries: number = 3
): Promise<T> {
  const url = `${backendManager.url}${endpoint}`

  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...options.headers
        }
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      return await response.json()
    } catch (error) {
      if (attempt === retries) {
        throw error
      }

      // Exponential backoff
      await new Promise(resolve => setTimeout(resolve, Math.pow(2, attempt) * 1000))
    }
  }

  throw new Error('Max retries exceeded')
}
