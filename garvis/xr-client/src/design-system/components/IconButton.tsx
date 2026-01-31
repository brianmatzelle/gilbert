/**
 * Design System IconButton Component
 * 
 * A small icon button for title bars and compact UI areas.
 */

import { useState, useMemo } from 'react'
import { Text } from '@react-three/drei'
import {
  colors,
  typography,
  radii,
  opacity,
  zLayers,
} from '../tokens'
import { createRoundedRectGeometry, type PointerEvent3D } from '../primitives'

export interface IconButtonProps {
  /** Icon/emoji to display */
  icon: string
  /** Tooltip/label (for accessibility, not displayed) */
  label?: string
  /** Button color variant */
  variant?: 'default' | 'success' | 'error' | 'muted'
  /** Whether button is in active/toggled state */
  active?: boolean
  /** Click handler */
  onPress: () => void
}

const variantColors = {
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

export function IconButton({
  icon,
  label,
  variant = 'default',
  active = false,
  onPress,
}: IconButtonProps) {
  const [hovered, setHovered] = useState(false)
  const [pressed, setPressed] = useState(false)

  const handlePointerDown = (e: PointerEvent3D) => {
    e.stopPropagation()
    setPressed(true)
  }

  const handlePointerUp = (e: PointerEvent3D) => {
    e.stopPropagation()
    if (pressed) onPress()
    setPressed(false)
  }

  const colorSet = variantColors[variant]
  const iconColor = pressed
    ? colors.interactive.active
    : hovered
      ? colorSet.hover
      : active
        ? colorSet.active
        : colorSet.base

  const bgOpacity = hovered || pressed ? opacity.medium : active ? opacity.light : 0

  const geometry = useMemo(
    () => createRoundedRectGeometry(0.025, 0.02, radii.sm),
    []
  )

  return (
    <group>
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
        {icon}
      </Text>
    </group>
  )
}

