import { createWorld } from 'koota'
import {
  ChatHistory,
  VoiceState,
  VisorConfig,
  SettingsUIState,
  ControlBarState,
  ActiveVideo,
  DEFAULT_VISOR_CONFIG,
  type VisorConfigData
} from './traits'

export const world = createWorld()

const STORAGE_KEY = 'garvis-visor-config'

function loadConfig(): VisorConfigData {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored) as Partial<VisorConfigData>
      return { ...DEFAULT_VISOR_CONFIG, ...parsed }
    }
  } catch (e) {
    console.warn('Failed to load visor config from localStorage:', e)
  }
  return DEFAULT_VISOR_CONFIG
}

export function saveConfig(config: VisorConfigData): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  } catch (e) {
    console.warn('Failed to save visor config to localStorage:', e)
  }
}

export function initializeWorld() {
  world.add(ChatHistory)
  world.set(ChatHistory, { messages: [] })

  world.add(VoiceState)
  world.set(VoiceState, {
    isListening: false,
    isSpeaking: false,
    isProcessing: false,
    isPaused: false,
    shouldReset: false,
    isConnected: false,
    error: null
  })

  const savedConfig = loadConfig()
  world.add(VisorConfig)
  world.set(VisorConfig, savedConfig)

  world.add(SettingsUIState)
  world.set(SettingsUIState, { isOpen: false })

  world.add(ControlBarState)
  world.set(ControlBarState, { isHovered: false })

  world.add(ActiveVideo)
  world.set(ActiveVideo, { url: null, isPlaying: false })
}

