/**
 * Design System Window Component
 * 
 * A draggable, resizable window container for XR interfaces.
 * Follows the camera and provides consistent chrome (title bar, close, resize).
 * Optionally persists position/scale to localStorage.
 */

import { useRef, useState, useCallback, useMemo, useEffect, type ReactNode } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Text } from '@react-three/drei'
import * as THREE from 'three'
import {
  colors,
  spacing,
  typography,
  radii,
  opacity,
  animation,
  zLayers,
  windowDefaults,
} from '../tokens'
import {
  createRoundedRectGeometry,
  type PointerEvent3D,
  type HorizontalMode,
} from '../primitives'

// ============================================================================
// STORAGE
// ============================================================================

const STORAGE_PREFIX = 'garvis-window-'

interface WindowState {
  offsetX: number
  offsetY: number
  offsetZ: number
  scale: number
}

function loadWindowState(key: string): WindowState | null {
  try {
    const stored = localStorage.getItem(STORAGE_PREFIX + key)
    if (stored) {
      return JSON.parse(stored)
    }
  } catch (e) {
    console.warn('Failed to load window state:', e)
  }
  return null
}

function saveWindowState(key: string, state: WindowState): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(state))
  } catch (e) {
    console.warn('Failed to save window state:', e)
  }
}

// ============================================================================
// TYPES
// ============================================================================

export interface WindowConfig {
  /** Base distance from camera */
  distance: number
  /** Horizontal offset from center */
  horizontalOffset: number
  /** Vertical offset from center */
  verticalOffset: number
  /** 'visor' = camera-locked HUD, 'yaw' = world-horizontal yaw-locked */
  horizontalMode: HorizontalMode
}

export interface WindowAction {
  /** Unique key for the action */
  key: string
  /** Icon/emoji to display */
  icon: string
  /** Color variant */
  variant?: 'default' | 'success' | 'error' | 'muted'
  /** Whether button shows active state */
  active?: boolean
  /** Click handler */
  onPress: () => void
}

export interface WindowProps {
  /** Window title shown in title bar */
  title: string
  /** Title bar icon/emoji */
  icon?: string
  /** Window width (content area) */
  width: number
  /** Window height (content area) */
  height: number
  /** Position/behavior config */
  config: WindowConfig
  /** Whether to show close button */
  showClose?: boolean
  /** Called when close button is pressed */
  onClose?: () => void
  /** Custom title bar actions (rendered before close button) */
  actions?: WindowAction[]
  /** Whether window can be dragged */
  draggable?: boolean
  /** Whether window can be resized */
  resizable?: boolean
  /** Min scale when resizing */
  minScale?: number
  /** Max scale when resizing */
  maxScale?: number
  /** Initial scale */
  initialScale?: number
  /** Background opacity */
  bgOpacity?: number
  /** localStorage key for persisting position/scale (omit to disable) */
  storageKey?: string
  /** Content to render inside the window */
  children: ReactNode
}

// ============================================================================
// ACTION BUTTON SUB-COMPONENT
// ============================================================================

const actionVariantColors = {
  default: {
    base: colors.text.secondary,
    hover: colors.accent.secondary,
    active: colors.accent.secondary,
  },
  success: {
    base: colors.success.base,
    hover: colors.success.hover,
    active: colors.success.hover,
  },
  error: {
    base: colors.error.base,
    hover: colors.error.hover,
    active: colors.error.hover,
  },
  muted: {
    base: colors.text.tertiary,
    hover: colors.text.secondary,
    active: colors.text.secondary,
  },
}

interface ActionButtonProps {
  action: WindowAction
  xOffset: number
}

function ActionButton({ action, xOffset }: ActionButtonProps) {
  const [hovered, setHovered] = useState(false)
  const [pressed, setPressed] = useState(false)

  const handlePointerDown = (e: PointerEvent3D) => {
    e.stopPropagation()
    setPressed(true)
  }

  const handlePointerUp = (e: PointerEvent3D) => {
    e.stopPropagation()
    if (pressed) action.onPress()
    setPressed(false)
  }

  const colorSet = actionVariantColors[action.variant ?? 'default']
  const iconColor = pressed
    ? colors.interactive.active
    : hovered
      ? colorSet.hover
      : action.active
        ? colorSet.active
        : colorSet.base

  const bgOpacity = hovered || pressed ? opacity.medium : action.active ? opacity.light : 0

  const geometry = useMemo(
    () => createRoundedRectGeometry(0.025, 0.02, radii.sm),
    []
  )

  return (
    <group position={[xOffset, 0, 0]}>
      <mesh
        geometry={geometry}
        onPointerDown={handlePointerDown}
        onPointerUp={handlePointerUp}
        onPointerEnter={() => setHovered(true)}
        onPointerLeave={() => { setHovered(false); setPressed(false) }}
      >
        <meshBasicMaterial
          color={iconColor}
          transparent
          opacity={bgOpacity}
        />
      </mesh>
      <Text
        position={[0, 0, zLayers.overlay]}
        fontSize={typography.fontSize.base}
        color={iconColor}
        anchorX="center"
        anchorY="middle"
      >
        {action.icon}
      </Text>
    </group>
  )
}

// ============================================================================
// WINDOW COMPONENT
// ============================================================================

export function Window({
  title,
  icon = '📋',
  width,
  height,
  config,
  showClose = true,
  onClose,
  actions = [],
  draggable = true,
  resizable = true,
  minScale = windowDefaults.minScale,
  maxScale = windowDefaults.maxScale,
  initialScale = 1.0,
  bgOpacity: bgOpacityProp = opacity.solid,
  storageKey,
  children,
}: WindowProps) {
  const { camera } = useThree()
  const groupRef = useRef<THREE.Group>(null)
  const initializedRef = useRef(false)

  // Position and scale state
  const [positionOffset, setPositionOffset] = useState(() => {
    // Try to load from storage on initial render
    if (storageKey) {
      const saved = loadWindowState(storageKey)
      if (saved) {
        return new THREE.Vector3(saved.offsetX, saved.offsetY, saved.offsetZ)
      }
    }
    return new THREE.Vector3(0, 0, 0)
  })

  const [scale, setScale] = useState(() => {
    // Try to load from storage on initial render
    if (storageKey) {
      const saved = loadWindowState(storageKey)
      if (saved) {
        return saved.scale
      }
    }
    return initialScale
  })

  // Mark as initialized after first render
  useEffect(() => {
    initializedRef.current = true
  }, [])

  // Interaction states
  const [isDragging, setIsDragging] = useState(false)
  const [isResizing, setIsResizing] = useState(false)
  const [dragHovered, setDragHovered] = useState(false)
  const [resizeHovered, setResizeHovered] = useState(false)
  const [closeHovered, setCloseHovered] = useState(false)

  // Refs for drag/resize calculations
  const dragStartRef = useRef<THREE.Vector3 | null>(null)
  const dragStartOffsetRef = useRef<THREE.Vector3 | null>(null)
  const resizeStartRef = useRef<{ point: THREE.Vector3; scale: number } | null>(null)

  // Dimensions
  const titleBarHeight = windowDefaults.titleBarHeight
  const padding = windowDefaults.padding
  const panelWidth = width + padding * 2
  const panelHeight = height + padding * 2 + titleBarHeight
  const handleSize = windowDefaults.resizeHandleSize

  // Calculate action buttons layout
  const actionButtonWidth = 0.03
  const totalActionsWidth = actions.length * actionButtonWidth
  const closeButtonWidth = showClose && onClose ? 0.045 : 0

  // ============================================================================
  // PERSISTENCE
  // ============================================================================

  const saveState = useCallback(() => {
    if (storageKey) {
      saveWindowState(storageKey, {
        offsetX: positionOffset.x,
        offsetY: positionOffset.y,
        offsetZ: positionOffset.z,
        scale,
      })
    }
  }, [storageKey, positionOffset, scale])

  // ============================================================================
  // DRAG HANDLERS
  // ============================================================================

  const handleDragStart = useCallback((e: PointerEvent3D) => {
    if (!draggable) return
    e.stopPropagation()
    setIsDragging(true)
    dragStartRef.current = e.point.clone()
    dragStartOffsetRef.current = positionOffset.clone()
    e.target?.setPointerCapture?.(e.pointerId)
  }, [draggable, positionOffset])

  const handleDragMove = useCallback((e: PointerEvent3D) => {
    if (!isDragging || !dragStartRef.current || !dragStartOffsetRef.current) return
    e.stopPropagation()
    const delta = e.point.clone().sub(dragStartRef.current)
    setPositionOffset(dragStartOffsetRef.current.clone().add(delta))
  }, [isDragging])

  const handleDragEnd = useCallback((e: PointerEvent3D) => {
    e.stopPropagation()
    setIsDragging(false)
    dragStartRef.current = null
    dragStartOffsetRef.current = null
    e.target?.releasePointerCapture?.(e.pointerId)
    // Save to localStorage after drag ends
    saveState()
  }, [saveState])

  // ============================================================================
  // RESIZE HANDLERS
  // ============================================================================

  const handleResizeStart = useCallback((e: PointerEvent3D) => {
    if (!resizable) return
    e.stopPropagation()
    setIsResizing(true)
    resizeStartRef.current = { point: e.point.clone(), scale }
    e.target?.setPointerCapture?.(e.pointerId)
  }, [resizable, scale])

  const handleResizeMove = useCallback((e: PointerEvent3D) => {
    if (!isResizing || !resizeStartRef.current) return
    e.stopPropagation()
    const startDist = resizeStartRef.current.point.length()
    const currentDist = e.point.length()
    const scaleFactor = currentDist / startDist
    const newScale = Math.max(minScale, Math.min(maxScale, resizeStartRef.current.scale * scaleFactor))
    setScale(newScale)
  }, [isResizing, minScale, maxScale])

  const handleResizeEnd = useCallback((e: PointerEvent3D) => {
    e.stopPropagation()
    setIsResizing(false)
    resizeStartRef.current = null
    e.target?.releasePointerCapture?.(e.pointerId)
    // Save to localStorage after resize ends
    saveState()
  }, [saveState])

  // ============================================================================
  // CAMERA FOLLOW (useFrame)
  // ============================================================================

  useFrame(() => {
    if (!groupRef.current) return

    const cameraPos = new THREE.Vector3()
    const cameraDir = new THREE.Vector3()
    const cameraWorldQuat = new THREE.Quaternion()

    camera.getWorldPosition(cameraPos)
    camera.getWorldDirection(cameraDir)
    camera.getWorldQuaternion(cameraWorldQuat)

    const mode = config.horizontalMode ?? 'visor'
    let targetPos: THREE.Vector3

    if (mode === 'yaw') {
      const horizontalDir = new THREE.Vector3(cameraDir.x, 0, cameraDir.z).normalize()
      const horizontalRight = new THREE.Vector3(-horizontalDir.z, 0, horizontalDir.x)

      targetPos = cameraPos
        .clone()
        .add(horizontalDir.multiplyScalar(config.distance))
        .add(horizontalRight.multiplyScalar(config.horizontalOffset))
        .add(new THREE.Vector3(0, config.verticalOffset, 0))
        .add(positionOffset)

      if (isDragging) {
        groupRef.current.position.copy(targetPos)
      } else {
        groupRef.current.position.lerp(targetPos, animation.lerpFactor)
      }
      groupRef.current.lookAt(cameraPos)
    } else {
      const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(cameraWorldQuat).normalize()
      const right = new THREE.Vector3(1, 0, 0).applyQuaternion(cameraWorldQuat).normalize()
      const up = new THREE.Vector3(0, 1, 0).applyQuaternion(cameraWorldQuat).normalize()

      targetPos = cameraPos
        .clone()
        .add(forward.multiplyScalar(config.distance))
        .add(right.multiplyScalar(config.horizontalOffset))
        .add(up.multiplyScalar(config.verticalOffset))
        .add(positionOffset)

      if (isDragging) {
        groupRef.current.position.copy(targetPos)
      } else {
        groupRef.current.position.lerp(targetPos, animation.lerpFactor)
      }
      groupRef.current.quaternion.slerp(cameraWorldQuat, animation.lerpFactor)
    }

    // Apply scale (instant during resize, smooth otherwise)
    if (isResizing) {
      groupRef.current.scale.setScalar(scale)
    } else {
      const currentScale = groupRef.current.scale.x
      groupRef.current.scale.setScalar(THREE.MathUtils.lerp(currentScale, scale, animation.lerpFactor))
    }
  })

  // ============================================================================
  // GEOMETRIES (memoized)
  // ============================================================================

  const panelRadius = Math.min(radii.xl, panelWidth * 0.05, panelHeight * 0.05)
  
  const panelGeometry = useMemo(
    () => createRoundedRectGeometry(panelWidth, panelHeight, panelRadius),
    [panelWidth, panelHeight, panelRadius]
  )

  const dragHandleGeometry = useMemo(
    () => createRoundedRectGeometry(panelWidth - 0.1, 0.03, radii.md),
    [panelWidth]
  )

  const closeButtonGeometry = useMemo(
    () => createRoundedRectGeometry(
      windowDefaults.closeButtonWidth,
      windowDefaults.closeButtonHeight,
      radii.md
    ),
    []
  )

  const resizeHandleGeometry = useMemo(
    () => new THREE.CircleGeometry(handleSize / 2, 16),
    [handleSize]
  )

  // ============================================================================
  // RENDER
  // ============================================================================

  return (
    <group ref={groupRef}>
      {/* Background panel */}
      <mesh geometry={panelGeometry} position={[0, 0, zLayers.background]}>
        <meshBasicMaterial
          color={colors.bg.primary}
          transparent
          opacity={bgOpacityProp}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* Title bar */}
      <group position={[0, panelHeight / 2 - titleBarHeight / 2, 0]}>
        {/* Drag handle */}
        {draggable && (
          <mesh
            geometry={dragHandleGeometry}
            position={[-spacing.md, 0, zLayers.overlay]}
            onPointerEnter={() => setDragHovered(true)}
            onPointerLeave={() => { setDragHovered(false); if (!isDragging) setIsDragging(false) }}
            onPointerDown={handleDragStart}
            onPointerMove={handleDragMove}
            onPointerUp={handleDragEnd}
          >
            <meshBasicMaterial
              color={dragHovered || isDragging ? colors.accent.secondary : colors.border.default}
              transparent
              opacity={dragHovered || isDragging ? opacity.medium : opacity.subtle}
            />
          </mesh>
        )}

        {/* Title text */}
        <Text
          position={[-panelWidth / 2 + spacing.lg, 0, zLayers.controls]}
          fontSize={typography.fontSize.xl}
          color={dragHovered || isDragging ? colors.accent.secondaryHover : colors.accent.secondary}
          anchorX="left"
          anchorY="middle"
        >
          {isDragging ? '✋ Moving' : `${icon} ${title}`}
        </Text>

        {/* Action buttons */}
        {actions.map((action, index) => (
          <ActionButton
            key={action.key}
            action={action}
            xOffset={panelWidth / 2 - closeButtonWidth - totalActionsWidth + (index * actionButtonWidth) + actionButtonWidth / 2}
          />
        ))}

        {/* Close button */}
        {showClose && onClose && (
          <group position={[panelWidth / 2 - 0.035, 0, 0]}>
            <mesh
              geometry={closeButtonGeometry}
              onPointerEnter={() => setCloseHovered(true)}
              onPointerLeave={() => setCloseHovered(false)}
              onPointerDown={(e) => { e.stopPropagation(); onClose() }}
            >
              <meshBasicMaterial
                color={closeHovered ? colors.error.base : colors.text.tertiary}
                transparent
                opacity={closeHovered ? opacity.medium : opacity.light}
              />
            </mesh>
            <Text
              position={[0, 0, zLayers.overlay]}
              fontSize={typography.fontSize.xl}
              color={closeHovered ? colors.error.base : colors.text.secondary}
              anchorX="center"
              anchorY="middle"
            >
              ✕
            </Text>
          </group>
        )}
      </group>

      {/* Content area */}
      <group position={[0, -titleBarHeight / 2, 0]}>
        {children}
      </group>

      {/* Resize handle */}
      {resizable && (
        <>
          <mesh
            geometry={resizeHandleGeometry}
            position={[
              panelWidth / 2 - handleSize / 2,
              -panelHeight / 2 + handleSize / 2,
              zLayers.tooltip
            ]}
            onPointerEnter={() => setResizeHovered(true)}
            onPointerLeave={() => { setResizeHovered(false); if (!isResizing) setIsResizing(false) }}
            onPointerDown={handleResizeStart}
            onPointerMove={handleResizeMove}
            onPointerUp={handleResizeEnd}
          >
            <meshBasicMaterial
              color={resizeHovered || isResizing ? colors.accent.secondary : colors.text.secondary}
              transparent
              opacity={resizeHovered || isResizing ? opacity.heavy : opacity.semi}
            />
          </mesh>
          <Text
            position={[
              panelWidth / 2 - handleSize / 2,
              -panelHeight / 2 + handleSize / 2,
              zLayers.modal
            ]}
            fontSize={typography.fontSize.lg}
            color={resizeHovered || isResizing ? colors.text.primary : colors.text.tertiary}
            anchorX="center"
            anchorY="middle"
          >
            ⤡
          </Text>
        </>
      )}
    </group>
  )
}
