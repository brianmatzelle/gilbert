import { useEffect, useRef, useCallback, useState } from 'react'
import {
  addMessage,
  updateMessage,
  setListening,
  setSpeaking,
  setProcessing,
  setConnected,
  setError,
  isPaused,
  consumeResetRequest,
  clearMessages,
  setActiveVideo
} from '../ecs/actions'
import { GarvisClient } from './garvis-client'

export function useVoiceAssistant(opts: { enabled: boolean }) {
  const { enabled } = opts

  const clientRef = useRef<GarvisClient | null>(null)
  const [isConnected, setIsConnectedState] = useState(false)
  const [error, setErrorState] = useState<string | null>(null)
  const [paused, setPaused] = useState(false)
  const hasConnectedOnce = useRef(false)
  const isReconnecting = useRef(false)

  // Track current streaming messages
  const currentUserTimestamp = useRef<number | null>(null)
  const currentAssistantTimestamp = useRef<number | null>(null)

  const createClient = useCallback(() => {
    return new GarvisClient({
      onConnected: () => {
        console.log('✅ Connected to Garvis voice server')
        setIsConnectedState(true)
        setConnected(true)
        setErrorState(null)
        setError(null)
      },
      onDisconnected: () => {
        console.log('❌ Disconnected from Garvis voice server')
        setIsConnectedState(false)
        setConnected(false)
        setListening(false)
        setSpeaking(false)
        setProcessing(false)
      },
      onError: (err) => {
        console.error('Garvis error:', err)
        setErrorState(err.message)
        setError(err.message)
      },
      onTranscript: (text, isFinal, role) => {
        if (role === 'user') {
          if (isFinal) {
            // Final user transcript - add as complete message
            if (currentUserTimestamp.current) {
              updateMessage('user', text, currentUserTimestamp.current)
            } else {
              addMessage('user', text)
            }
            currentUserTimestamp.current = null
          } else {
            // Interim user transcript - create or update streaming message
            if (!currentUserTimestamp.current) {
              currentUserTimestamp.current = Date.now()
            }
            updateMessage('user', text, currentUserTimestamp.current)
          }
        } else {
          // Assistant transcript
          if (isFinal) {
            // Final assistant transcript
            if (currentAssistantTimestamp.current) {
              updateMessage('assistant', text, currentAssistantTimestamp.current)
            } else {
              addMessage('assistant', text)
            }
            currentAssistantTimestamp.current = null
          } else {
            // Streaming assistant transcript
            if (!currentAssistantTimestamp.current) {
              currentAssistantTimestamp.current = Date.now()
            }
            updateMessage('assistant', text, currentAssistantTimestamp.current)
          }
        }
      },
      onListening: (listening) => {
        setListening(listening)
        if (listening) {
          setProcessing(false)
        }
      },
      onSpeaking: (speaking) => {
        setSpeaking(speaking)
        if (speaking) {
          setProcessing(false)
        } else if (!speaking) {
          setProcessing(true)
        }
      },
      onStreamUrl: (url) => {
        console.log('📺 Opening video stream:', url)
        // Defer to next tick to avoid state update during render
        setTimeout(() => {
          try {
            setActiveVideo(url)
          } catch (err) {
            console.error('📺 Failed to set active video:', err)
          }
        }, 0)
      }
    })
  }, [])

  const connect = useCallback(async () => {
    if (!enabled) return

    if (clientRef.current?.isConnected() || isReconnecting.current) {
      return
    }

    if (clientRef.current) {
      clientRef.current.disconnect()
      clientRef.current = null
    }

    clientRef.current = createClient()

    try {
      await clientRef.current.connect()
      hasConnectedOnce.current = true
    } catch (err) {
      console.error('Failed to connect:', err)
      setErrorState(err instanceof Error ? err.message : 'Connection failed')
      setError(err instanceof Error ? err.message : 'Connection failed')
    }
  }, [createClient, enabled])

  const disconnect = useCallback(() => {
    if (clientRef.current) {
      clientRef.current.disconnect()
      clientRef.current = null
    }
  }, [])

  // Poll pause state + reset requests from Koota
  useEffect(() => {
    const interval = setInterval(async () => {
      const currentPaused = isPaused()
      if (currentPaused !== paused) {
        setPaused(currentPaused)
      }

      if (
        consumeResetRequest() &&
        clientRef.current &&
        isConnected &&
        !isReconnecting.current
      ) {
        isReconnecting.current = true
        try {
          // Clear messages and reconnect
          clearMessages()
          clientRef.current.disconnect()
          clientRef.current = createClient()
          await clientRef.current.connect()
        } catch (err) {
          console.error('Failed to reconnect:', err)
          setErrorState(err instanceof Error ? err.message : 'Reconnect failed')
        } finally {
          isReconnecting.current = false
        }
      }
    }, 100)

    return () => clearInterval(interval)
  }, [paused, isConnected, createClient])

  // Pause/resume behavior
  useEffect(() => {
    if (!enabled) return

    if (paused) {
      if (!isReconnecting.current) {
        disconnect()
      }
    } else if (hasConnectedOnce.current && !isConnected && !isReconnecting.current) {
      connect()
    }
  }, [paused, isConnected, connect, disconnect, enabled])

  // Start/stop with XR session
  useEffect(() => {
    if (!enabled) {
      disconnect()
      return
    }

    const timeout = setTimeout(() => {
      if (!isPaused()) {
        connect()
      }
    }, 750)

    return () => {
      clearTimeout(timeout)
      disconnect()
    }
  }, [enabled, connect, disconnect])

  return { isConnected, error, paused }
}
