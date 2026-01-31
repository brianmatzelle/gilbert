/**
 * Chat Content Component
 * 
 * The inner content of the chat window - messages, status, scroll buttons.
 */

import { useState, useEffect, useMemo, useRef } from 'react'
import { Text } from '@react-three/drei'
import * as THREE from 'three'
import { world } from '../../ecs/world'
import { ChatHistory, VoiceState, type ChatMessage, type VisorConfigData } from '../../ecs/traits'
import {
  colors,
  typography,
  radii,
  opacity,
  zLayers,
  createRoundedRectGeometry,
} from '../../design-system'

interface ChatContentProps {
  config: VisorConfigData
}

export function ChatContent({ config }: ChatContentProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [voiceState, setVoiceState] = useState({
    isListening: false,
    isSpeaking: false,
    isProcessing: false,
    isPaused: false,
    isConnected: false,
    error: null as string | null,
  })

  const [scrollOffset, setScrollOffset] = useState(0)
  const [scrollUpHovered, setScrollUpHovered] = useState(false)
  const [scrollDownHovered, setScrollDownHovered] = useState(false)
  const prevMessageCount = useRef(0)

  // Content dimensions
  const contentWidth = config.maxWidth
  const MAX_CHAT_HEIGHT = 0.18

  const baseFontSize = typography.fontSize.sm * config.fontSize
  const statusFontSize = typography.fontSize.base * config.fontSize
  const lineHeight = 0.012 * config.fontSize
  const messageGap = 0

  // Poll ECS state
  useEffect(() => {
    const interval = setInterval(() => {
      const history = world.get(ChatHistory)
      if (history) setMessages([...history.messages])
      const state = world.get(VoiceState)
      if (state) setVoiceState({ ...state })
    }, 50)
    return () => clearInterval(interval)
  }, [])

  const formatMessage = (msg: ChatMessage) => {
    const prefix = msg.role === 'user' ? 'You: ' : 'Garvis: '
    return prefix + msg.content
  }

  const estimateMessageHeight = (text: string) => {
    const avgCharWidth = 0.0035 * config.fontSize
    const charsPerLine = Math.floor(contentWidth / avgCharWidth)
    const lineCount = Math.max(1, Math.ceil(text.length / charsPerLine))
    return lineCount * lineHeight * config.fontSize + messageGap
  }

  const sortedMessages = useMemo(
    () => [...messages].sort((a, b) => a.timestamp - b.timestamp),
    [messages]
  )

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (sortedMessages.length > prevMessageCount.current) {
      setScrollOffset(0)
    }
    prevMessageCount.current = sortedMessages.length
  }, [sortedMessages.length])

  // Calculate visible messages and scroll state
  const { displayMessages, messagePositions, canScrollUp, canScrollDown, maxScrollOffset } = useMemo(() => {
    if (sortedMessages.length === 0) {
      return { displayMessages: [], messagePositions: [], canScrollUp: false, canScrollDown: false, maxScrollOffset: 0 }
    }

    const endIndex = sortedMessages.length - scrollOffset
    let totalHeight = 0
    let startIndex = endIndex

    for (let i = endIndex - 1; i >= 0; i--) {
      const msgHeight = estimateMessageHeight(formatMessage(sortedMessages[i]))
      if (totalHeight + msgHeight > MAX_CHAT_HEIGHT) break
      totalHeight += msgHeight
      startIndex = i
    }

    const visible = sortedMessages.slice(startIndex, endIndex)
    const positions: number[] = []
    let currentY = MAX_CHAT_HEIGHT / 2 - 0.01

    for (const msg of visible) {
      positions.push(currentY)
      currentY -= estimateMessageHeight(formatMessage(msg))
    }

    let maxScroll = 0
    if (scrollOffset === 0) {
      maxScroll = sortedMessages.length - visible.length
    } else {
      let h = 0
      let count = 0
      for (let i = sortedMessages.length - 1; i >= 0; i--) {
        const msgHeight = estimateMessageHeight(formatMessage(sortedMessages[i]))
        if (h + msgHeight > MAX_CHAT_HEIGHT) break
        h += msgHeight
        count++
      }
      maxScroll = sortedMessages.length - count
    }

    return {
      displayMessages: visible,
      messagePositions: positions,
      canScrollUp: startIndex > 0,
      canScrollDown: scrollOffset > 0,
      maxScrollOffset: maxScroll,
    }
  }, [sortedMessages, scrollOffset, config.fontSize, contentWidth, MAX_CHAT_HEIGHT])

  const handleScrollUp = () => {
    if (canScrollUp) setScrollOffset((prev) => Math.min(prev + 1, maxScrollOffset))
  }

  const handleScrollDown = () => {
    if (canScrollDown) setScrollOffset((prev) => Math.max(prev - 1, 0))
  }

  const getStatusText = () => {
    if (!voiceState.isConnected) return '🔴 Disconnected'
    if (voiceState.error) return `❌ ${voiceState.error}`
    if (voiceState.isPaused) return '🔇 Paused'
    if (voiceState.isListening) return '🎤 Listening...'
    if (voiceState.isProcessing) return '🤔 Thinking...'
    if (voiceState.isSpeaking) return '🔊 Speaking...'
    return '🟢 Ready'
  }

  // Geometries
  const scrollButtonGeometry = useMemo(
    () => createRoundedRectGeometry(0.015, 0.01, radii.sm),
    []
  )

  // Colors
  const scrollUpColor = scrollUpHovered ? colors.accent.secondary : colors.text.secondary
  const scrollDownColor = scrollDownHovered ? colors.accent.secondary : colors.text.secondary
  const scrollUpOpacity = canScrollUp ? (scrollUpHovered ? opacity.medium : 0) : 0
  const scrollDownOpacity = canScrollDown ? (scrollDownHovered ? opacity.medium : 0) : 0

  // Positions
  const contentLeft = -contentWidth / 2
  const statusY = MAX_CHAT_HEIGHT / 2 + 0.015

  return (
    <group>
      {/* Status bar */}
      <Text
        position={[contentLeft, statusY, 0]}
        fontSize={statusFontSize}
        color={colors.text.secondary}
        anchorX="left"
        anchorY="middle"
      >
        {getStatusText()}
      </Text>

      {/* Scroll up button */}
      {canScrollUp && (
        <group position={[contentLeft - 0.015, MAX_CHAT_HEIGHT / 2 - 0.01, 0]}>
          <mesh
            geometry={scrollButtonGeometry}
            onPointerEnter={() => setScrollUpHovered(true)}
            onPointerLeave={() => setScrollUpHovered(false)}
            onPointerDown={(e) => { e.stopPropagation(); handleScrollUp() }}
          >
            <meshBasicMaterial color={scrollUpColor} transparent opacity={scrollUpOpacity} />
          </mesh>
          <Text
            position={[0, 0, zLayers.overlay]}
            fontSize={baseFontSize * 0.9}
            color={scrollUpColor}
            anchorX="center"
            anchorY="middle"
          >
            ▲
          </Text>
        </group>
      )}

      {/* Messages */}
      {displayMessages.map((msg, i) => (
        <Text
          key={msg.timestamp}
          position={[contentLeft, messagePositions[i], 0]}
          fontSize={baseFontSize}
          color={msg.role === 'user' ? colors.text.user : colors.text.assistant}
          anchorX="left"
          anchorY="top"
          maxWidth={contentWidth}
        >
          {formatMessage(msg)}
        </Text>
      ))}

      {/* Scroll down button */}
      {canScrollDown && (
        <group position={[contentLeft - 0.015, -MAX_CHAT_HEIGHT / 2 + 0.01, 0]}>
          <mesh
            geometry={scrollButtonGeometry}
            onPointerEnter={() => setScrollDownHovered(true)}
            onPointerLeave={() => setScrollDownHovered(false)}
            onPointerDown={(e) => { e.stopPropagation(); handleScrollDown() }}
          >
            <meshBasicMaterial color={scrollDownColor} transparent opacity={scrollDownOpacity} />
          </mesh>
          <Text
            position={[0, 0, zLayers.overlay]}
            fontSize={baseFontSize * 0.9}
            color={scrollDownColor}
            anchorX="center"
            anchorY="middle"
          >
            ▼
          </Text>
        </group>
      )}

      {/* Empty state */}
      {messages.length === 0 && (
        <Text
          position={[contentLeft, 0, 0]}
          fontSize={baseFontSize}
          color={colors.text.tertiary}
          anchorX="left"
          anchorY="middle"
        >
          Say something to start...
        </Text>
      )}
    </group>
  )
}
