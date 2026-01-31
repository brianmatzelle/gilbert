/**
 * Design System Button Component
 * 
 * A reusable 3D button for XR interfaces.
 */

import { useState, useMemo } from 'react'
import { Text } from '@react-three/drei'
import * as THREE from 'three'
import { colors, typography, radii, opacity } from '../tokens'
import { createRoundedRectGeometry, type PointerEvent3D } from '../primitives'

export interface ButtonProps {
  /** Button label text */
  label: string
  /** Position in 3D space */
  position?: [number, number, number]
  /** Button width */
  width?: number
  /** Button height */
  height?: number
  /** Button color variant */
  variant?: 'primary' | 'secondary' | 'success' | 'error'
  /** Whether button is disabled */
  disabled?: boolean
  /** Click handler */
  onPress: () => void
}

const variantColors = {
  primary: { base: colors.accent.primary, hover: colors.accent.primaryHover },
  secondary: { base: colors.accent.secondary, hover: colors.accent.secondaryHover },
  success: { base: colors.success.base, hover: colors.success.hover },
  error: { base: colors.error.base, hover: colors.error.hover },
}

export function Button({
  label,
  position = [0, 0, 0],
  width = 0.07,
  height = 0.025,
  variant = 'primary',
  disabled = false,
  onPress,
}: ButtonProps) {
  const [hovered, setHovered] = useState(false)
  const [pressed, setPressed] = useState(false)

  const handlePointerDown = (e: PointerEvent3D) => {
    e.stopPropagation()
    if (!disabled) setPressed(true)
  }

  const handlePointerUp = (e: PointerEvent3D) => {
    e.stopPropagation()
    if (!disabled && pressed) onPress()
    setPressed(false)
  }

  const colorSet = variantColors[variant]
  const currentColor = disabled
    ? colors.interactive.disabled
    : pressed
      ? colors.interactive.active
      : hovered
        ? colorSet.hover
        : colorSet.base

  const textColor = disabled ? colors.text.disabled : colors.text.primary

  const geometry = useMemo(
    () => createRoundedRectGeometry(width, height, radii.md),
    [width, height]
  )

  return (
    <group position={position}>
      <mesh
        geometry={geometry}
        onPointerDown={handlePointerDown}
        onPointerUp={handlePointerUp}
        onPointerEnter={() => !disabled && setHovered(true)}
        onPointerLeave={() => { setHovered(false); setPressed(false) }}
      >
        <meshBasicMaterial color={currentColor} />
      </mesh>
      <Text
        position={[0, 0, 0.001]}
        fontSize={typography.fontSize.base}
        color={textColor}
        anchorX="center"
        anchorY="middle"
      >
        {label}
      </Text>
    </group>
  )
}

