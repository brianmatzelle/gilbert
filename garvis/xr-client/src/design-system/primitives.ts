/**
 * Design System Primitives
 * 
 * Low-level utilities and types used across the design system.
 */

import * as THREE from 'three'

// ============================================================================
// TYPES
// ============================================================================

/**
 * R3F pointer event type with 3D point information
 */
export type PointerEvent3D = THREE.Event & {
  point: THREE.Vector3
  pointerId: number
  stopPropagation: () => void
  target: {
    setPointerCapture?: (pointerId: number) => void
    releasePointerCapture?: (pointerId: number) => void
  }
}

/**
 * Window horizontal positioning mode
 */
export type HorizontalMode = 'visor' | 'yaw'

// ============================================================================
// SHAPE UTILITIES
// ============================================================================

/**
 * Creates a rounded rectangle shape for use with ShapeGeometry
 */
export function createRoundedRectShape(
  width: number,
  height: number,
  radius: number
): THREE.Shape {
  const shape = new THREE.Shape()
  const x = -width / 2
  const y = -height / 2

  // Clamp radius to not exceed half of smallest dimension
  const r = Math.min(radius, width / 2, height / 2)

  shape.moveTo(x + r, y)
  shape.lineTo(x + width - r, y)
  shape.quadraticCurveTo(x + width, y, x + width, y + r)
  shape.lineTo(x + width, y + height - r)
  shape.quadraticCurveTo(x + width, y + height, x + width - r, y + height)
  shape.lineTo(x + r, y + height)
  shape.quadraticCurveTo(x, y + height, x, y + height - r)
  shape.lineTo(x, y + r)
  shape.quadraticCurveTo(x, y, x + r, y)

  return shape
}

/**
 * Creates a ShapeGeometry from rounded rect parameters
 */
export function createRoundedRectGeometry(
  width: number,
  height: number,
  radius: number
): THREE.ShapeGeometry {
  return new THREE.ShapeGeometry(createRoundedRectShape(width, height, radius))
}

// ============================================================================
// CAMERA UTILITIES
// ============================================================================

/**
 * Calculates target position for camera-following elements
 */
export function calculateCameraFollowPosition(
  camera: THREE.Camera,
  distance: number,
  horizontalOffset: number,
  verticalOffset: number,
  mode: HorizontalMode
): { position: THREE.Vector3; quaternion: THREE.Quaternion } {
  const cameraPos = new THREE.Vector3()
  const cameraDir = new THREE.Vector3()
  const cameraWorldQuat = new THREE.Quaternion()

  camera.getWorldPosition(cameraPos)
  camera.getWorldDirection(cameraDir)
  camera.getWorldQuaternion(cameraWorldQuat)

  let targetPos: THREE.Vector3
  let targetQuat: THREE.Quaternion

  if (mode === 'yaw') {
    // World-horizontal yaw-locked mode
    const horizontalDir = new THREE.Vector3(cameraDir.x, 0, cameraDir.z).normalize()
    const horizontalRight = new THREE.Vector3(-horizontalDir.z, 0, horizontalDir.x)

    targetPos = cameraPos
      .clone()
      .add(horizontalDir.multiplyScalar(distance))
      .add(horizontalRight.multiplyScalar(horizontalOffset))
      .add(new THREE.Vector3(0, verticalOffset, 0))

    // Look at camera for yaw mode
    const lookAtQuat = new THREE.Quaternion()
    const lookAtMatrix = new THREE.Matrix4().lookAt(targetPos, cameraPos, new THREE.Vector3(0, 1, 0))
    lookAtQuat.setFromRotationMatrix(lookAtMatrix)
    targetQuat = lookAtQuat
  } else {
    // Camera-locked visor/HUD mode
    const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(cameraWorldQuat).normalize()
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(cameraWorldQuat).normalize()
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(cameraWorldQuat).normalize()

    targetPos = cameraPos
      .clone()
      .add(forward.multiplyScalar(distance))
      .add(right.multiplyScalar(horizontalOffset))
      .add(up.multiplyScalar(verticalOffset))

    targetQuat = cameraWorldQuat.clone()
  }

  return { position: targetPos, quaternion: targetQuat }
}

