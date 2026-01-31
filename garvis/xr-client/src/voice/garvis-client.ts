/**
 * Garvis Voice Client
 * 
 * WebSocket-based voice streaming client for the Garvis XR assistant.
 * Handles:
 * - Microphone capture and streaming
 * - Real-time transcript updates
 * - TTS audio playback
 */

export interface GarvisEvents {
  onConnected?: () => void
  onDisconnected?: () => void
  onError?: (error: Error) => void
  onTranscript?: (text: string, isFinal: boolean, role: 'user' | 'assistant') => void
  onListening?: (isListening: boolean) => void
  onSpeaking?: (isSpeaking: boolean) => void
  onStreamUrl?: (url: string) => void
}

export class GarvisClient {
  private ws: WebSocket | null = null
  private micStream: MediaStream | null = null
  private captureContext: AudioContext | null = null
  private events: GarvisEvents
  
  // Audio playback
  private audioElement: HTMLAudioElement | null = null
  private audioQueue: ArrayBuffer[] = []
  private pendingUrls: string[] = []
  private isSpeaking: boolean = false

  constructor(events: GarvisEvents = {}) {
    this.events = events
  }

  async connect(wsUrl: string = '/ws/voice'): Promise<void> {
    try {
      // Request microphone access first
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      })

      // Setup audio playback
      this.setupAudioPlayback()

      // Connect WebSocket
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.host
      const fullUrl = wsUrl.startsWith('/') ? `${protocol}//${host}${wsUrl}` : wsUrl
      
      this.ws = new WebSocket(fullUrl)
      this.ws.binaryType = 'arraybuffer'

      this.ws.onopen = () => {
        console.log('✅ Connected to Garvis voice server')
        this.events.onConnected?.()
        this.startMicrophoneStreaming()
      }

      this.ws.onmessage = async (event) => {
        if (event.data instanceof ArrayBuffer) {
          // Binary audio data from TTS (MP3)
          this.handleAudioData(event.data)
        } else {
          // JSON message
          try {
            const message = JSON.parse(event.data)
            this.handleServerMessage(message)
          } catch (e) {
            console.error('Failed to parse server message:', e)
          }
        }
      }

      this.ws.onclose = () => {
        console.log('❌ Disconnected from Garvis voice server')
        this.events.onDisconnected?.()
        this.cleanup()
      }

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        this.events.onError?.(new Error('WebSocket connection error'))
      }

    } catch (error) {
      console.error('Failed to connect:', error)
      this.events.onError?.(error as Error)
      throw error
    }
  }

  private setupAudioPlayback(): void {
    this.audioElement = new Audio()
    this.audioElement.autoplay = false
    
    // When audio ends, play next in queue
    this.audioElement.onended = () => {
      this.playNextInQueue()
    }
  }

  disconnect(): void {
    this.stopMicrophoneStreaming()
    
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }

    this.cleanup()
    this.events.onDisconnected?.()
  }

  private cleanup(): void {
    if (this.micStream) {
      this.micStream.getTracks().forEach(track => track.stop())
      this.micStream = null
    }

    if (this.captureContext) {
      this.captureContext.close()
      this.captureContext = null
    }

    if (this.audioElement) {
      this.audioElement.pause()
      this.audioElement.src = ''
      this.audioElement = null
    }

    // Clean up blob URLs
    for (const url of this.pendingUrls) {
      URL.revokeObjectURL(url)
    }
    this.pendingUrls = []
    this.audioQueue = []
  }

  private startMicrophoneStreaming(): void {
    if (!this.micStream || !this.ws) return
    this.setupMicCapture()
  }

  private async setupMicCapture(): Promise<void> {
    if (!this.micStream) return

    try {
      // Create a capture context at 16kHz for mic
      this.captureContext = new AudioContext({ sampleRate: 16000 })
      const source = this.captureContext.createMediaStreamSource(this.micStream)
      const processor = this.captureContext.createScriptProcessor(4096, 1, 1)

      processor.onaudioprocess = (e) => {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return

        const inputData = e.inputBuffer.getChannelData(0)
        
        // Convert to 16-bit PCM
        const pcmData = this.floatTo16BitPCM(inputData)
        
        // Send to server
        this.ws.send(pcmData.buffer)
      }

      source.connect(processor)
      processor.connect(this.captureContext.destination)

    } catch (error) {
      console.error('Failed to setup mic capture:', error)
      this.events.onError?.(error as Error)
    }
  }

  private stopMicrophoneStreaming(): void {
    // Cleanup handled in cleanup()
  }

  private floatTo16BitPCM(input: Float32Array): Int16Array {
    const output = new Int16Array(input.length)
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]))
      output[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    }
    return output
  }

  private handleServerMessage(message: Record<string, unknown>): void {
    const type = message.type as string

    switch (type) {
      case 'transcript':
        this.events.onTranscript?.(
          message.text as string,
          message.is_final as boolean,
          message.role as 'user' | 'assistant'
        )
        break

      case 'status': {
        this.events.onListening?.(message.listening as boolean)
        this.events.onSpeaking?.(message.speaking as boolean)
        
        // Track speaking state for audio buffering
        const wasSpeaking = this.isSpeaking
        this.isSpeaking = message.speaking as boolean
        
        // When speaking stops, flush ALL accumulated audio and play as one piece
        if (wasSpeaking && !this.isSpeaking) {
          this.flushAudioQueue()
        }
        break
      }

      case 'error':
        this.events.onError?.(new Error(message.message as string))
        break

      case 'stream_url':
        console.log('📺 Received stream URL:', message.url)
        this.events.onStreamUrl?.(message.url as string)
        break
    }
  }

  private handleAudioData(data: ArrayBuffer): void {
    // Queue ALL audio chunks - don't flush until speaking ends
    // This prevents stuttering from playing partial MP3 fragments
    this.audioQueue.push(data)
  }

  private flushAudioQueue(): void {
    if (this.audioQueue.length === 0) return

    // Combine all queued chunks
    const totalLength = this.audioQueue.reduce((sum, chunk) => sum + chunk.byteLength, 0)
    const combined = new Uint8Array(totalLength)
    let offset = 0
    for (const chunk of this.audioQueue) {
      combined.set(new Uint8Array(chunk), offset)
      offset += chunk.byteLength
    }
    this.audioQueue = []

    // Create blob URL and queue for playback
    const blob = new Blob([combined], { type: 'audio/mpeg' })
    const url = URL.createObjectURL(blob)
    this.pendingUrls.push(url)
    
    // If not currently playing, start
    if (this.audioElement && (this.audioElement.paused || this.audioElement.ended)) {
      this.playNextInQueue()
    }
  }

  private playNextInQueue(): void {
    if (!this.audioElement || this.pendingUrls.length === 0) return
    
    // Revoke the previous URL if any
    const currentSrc = this.audioElement.src
    if (currentSrc && currentSrc.startsWith('blob:')) {
      URL.revokeObjectURL(currentSrc)
    }
    
    // Get next URL and play
    const nextUrl = this.pendingUrls.shift()!
    this.audioElement.src = nextUrl
    this.audioElement.play().catch(e => {
      console.error('Audio play error:', e)
      // Try next one
      this.playNextInQueue()
    })
  }

  sendControl(type: string, data: Record<string, unknown> = {}): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, ...data }))
    }
  }

  interrupt(): void {
    this.sendControl('interrupt')
    
    if (this.audioElement) {
      this.audioElement.pause()
      this.audioElement.src = ''
    }
    
    // Clean up pending URLs
    for (const url of this.pendingUrls) {
      URL.revokeObjectURL(url)
    }
    this.pendingUrls = []
    this.audioQueue = []
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}
