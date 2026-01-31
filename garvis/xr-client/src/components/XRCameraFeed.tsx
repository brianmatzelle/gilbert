import { useRef, useMemo, useEffect } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useXR } from '@react-three/xr'
import { Text } from '@react-three/drei'
import * as THREE from 'three'
import type { XRCameraState } from '../hooks/useXRCamera'
import type { FaceDetectionData } from '../hooks/useFaceDetection'
import type { Detection } from '../hooks/useDetection'

// ============================================================
// Overlay Positioning Configuration
// ============================================================
// These values were tuned heuristically on Quest 3 to align
// bounding box overlays with real-world objects. The camera's
// field of view doesn't perfectly match the passthrough view,
// so we position the invisible overlay plane to best approximate
// where detected faces appear in physical space.

const OVERLAY_CONFIG = {
  // Distance from user's eyes to the overlay plane (meters)
  // Larger = further away, reduces stereo disparity mismatch
  distance: 0.6,
  
  // Horizontal offset from center (meters)
  // Positive = right, negative = left
  // Compensates for camera being slightly off-center from eyes
  xOffset: 0.04,
  
  // Vertical offset from eye level (meters)
  // Negative = below eye level (camera is typically lower than eyes)
  yOffset: -0.130,
  
  // Base height of the overlay plane (meters)
  // Width is calculated from camera aspect ratio
  planeHeight: 0.2,
  
  // Scale factor: keeps apparent size constant as distance changes
  // baseDistance is the reference distance where scale = 1
  baseDistance: 0.18,
}

// Bounding box colors for faces
const COLORS = {
  face: '#00ffff',
  label: '#00ffff',
  labelBg: '#000000',
}

// Color palette for different object classes (YOLO detection)
// Note: Face detection uses #00ffff (cyan), so avoid that color here
const CLASS_COLORS: Record<string, string> = {
  person: '#ff9f1c',    // Orange (distinct from cyan face boxes)
  car: '#ff6b6b',
  truck: '#ff6b6b',
  bus: '#ff6b6b',
  bicycle: '#4ecdc4',
  motorcycle: '#4ecdc4',
  dog: '#ffe66d',
  cat: '#ffe66d',
  bird: '#ffe66d',
  laptop: '#a855f7',
  cell_phone: '#a855f7',
  tv: '#a855f7',
  cup: '#22c55e',
  bottle: '#22c55e',
  chair: '#f59e0b',
  couch: '#f59e0b',
  bed: '#f59e0b',
  book: '#8b5cf6',
  clock: '#ec4899',
  default: '#39ff14',
}

function getClassColor(className: string): string {
  return CLASS_COLORS[className.toLowerCase()] || CLASS_COLORS.default
}

// ============================================================
// Components
// ============================================================

interface BoundingBoxProps {
  detection: FaceDetectionData
  imageSize: { width: number; height: number }
  planeWidth: number
  planeHeight: number
}

/**
 * Single bounding box overlay for a detected face
 */
function BoundingBox({ detection, imageSize, planeWidth, planeHeight }: BoundingBoxProps) {
  const { bbox, confidence } = detection
  const color = COLORS.face
  
  // Convert pixel coordinates to plane coordinates
  // Image: origin top-left, Y increases downward
  // Plane: origin center, Y increases upward
  const pixelToPlane = (px: number, py: number) => {
    const nx = px / imageSize.width
    const ny = py / imageSize.height
    const x = (nx - 0.5) * planeWidth
    const y = (0.5 - ny) * planeHeight
    return { x, y }
  }
  
  const topLeft = pixelToPlane(bbox.x1, bbox.y1)
  const bottomRight = pixelToPlane(bbox.x2, bbox.y2)
  
  const centerX = (topLeft.x + bottomRight.x) / 2
  const centerY = (topLeft.y + bottomRight.y) / 2
  const width = Math.abs(bottomRight.x - topLeft.x)
  const height = Math.abs(topLeft.y - bottomRight.y)
  
  const label = `${Math.round(confidence * 100)}%`
  const lineWidth = 0.0004

  return (
    <group position={[centerX, centerY, 0.001]}>
      {/* Box edges */}
      <mesh position={[0, height / 2, 0]}>
        <planeGeometry args={[width, lineWidth]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <mesh position={[0, -height / 2, 0]}>
        <planeGeometry args={[width, lineWidth]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <mesh position={[-width / 2, 0, 0]}>
        <planeGeometry args={[lineWidth, height]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <mesh position={[width / 2, 0, 0]}>
        <planeGeometry args={[lineWidth, height]} />
        <meshBasicMaterial color={color} />
      </mesh>
      
      {/* Corner accents */}
      <CornerAccents width={width} height={height} color={color} />
      
      {/* Label */}
      <group position={[-width / 2 + 0.02, height / 2 + 0.008, 0.001]}>
        <mesh position={[0, 0, -0.0005]}>
          <planeGeometry args={[0.04, 0.012]} />
          <meshBasicMaterial color={COLORS.labelBg} transparent opacity={0.8} />
        </mesh>
        <Text
          fontSize={0.007}
          color={COLORS.label}
          anchorX="center"
          anchorY="middle"
        >
          {label}
        </Text>
      </group>
    </group>
  )
}

function CornerAccents({ width, height, color }: { width: number; height: number; color: string }) {
  const size = 0.008
  const thickness = 0.0008
  
  const corners = [
    { x: -width / 2, y: height / 2, rotH: 0, rotV: 0 },      // top-left
    { x: width / 2, y: height / 2, rotH: 0, rotV: Math.PI }, // top-right
    { x: -width / 2, y: -height / 2, rotH: Math.PI, rotV: 0 }, // bottom-left
    { x: width / 2, y: -height / 2, rotH: Math.PI, rotV: Math.PI }, // bottom-right
  ]
  
  return (
    <>
      {corners.map((corner, i) => (
        <group key={i} position={[corner.x, corner.y, 0.0002]}>
          {/* Horizontal accent */}
          <mesh position={[corner.rotV ? -size / 2 : size / 2, 0, 0]}>
            <planeGeometry args={[size, thickness * 2]} />
            <meshBasicMaterial color={color} />
          </mesh>
          {/* Vertical accent */}
          <mesh position={[0, corner.rotH ? size / 2 : -size / 2, 0]}>
            <planeGeometry args={[thickness * 2, size]} />
            <meshBasicMaterial color={color} />
          </mesh>
        </group>
      ))}
    </>
  )
}

// ============================================================
// Object Detection Bounding Box (YOLO)
// ============================================================

interface ObjectBoundingBoxProps {
  detection: Detection
  imageSize: { width: number; height: number }
  planeWidth: number
  planeHeight: number
}

/**
 * Single bounding box overlay for a detected object (YOLO)
 */
function ObjectBoundingBox({ detection, imageSize, planeWidth, planeHeight }: ObjectBoundingBoxProps) {
  const { bbox, confidence } = detection
  const className = detection.class
  const color = getClassColor(className)
  
  // Convert pixel coordinates to plane coordinates
  const pixelToPlane = (px: number, py: number) => {
    const nx = px / imageSize.width
    const ny = py / imageSize.height
    const x = (nx - 0.5) * planeWidth
    const y = (0.5 - ny) * planeHeight
    return { x, y }
  }
  
  const topLeft = pixelToPlane(bbox.x1, bbox.y1)
  const bottomRight = pixelToPlane(bbox.x2, bbox.y2)
  
  const centerX = (topLeft.x + bottomRight.x) / 2
  const centerY = (topLeft.y + bottomRight.y) / 2
  const width = Math.abs(bottomRight.x - topLeft.x)
  const height = Math.abs(topLeft.y - bottomRight.y)
  
  const label = `${className} ${Math.round(confidence * 100)}%`
  const lineWidth = 0.00035

  return (
    <group position={[centerX, centerY, 0.002]}>
      {/* Bounding box outline */}
      <mesh position={[0, height / 2 - lineWidth / 2, 0]}>
        <planeGeometry args={[width, lineWidth]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <mesh position={[0, -height / 2 + lineWidth / 2, 0]}>
        <planeGeometry args={[width, lineWidth]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <mesh position={[-width / 2 + lineWidth / 2, 0, 0]}>
        <planeGeometry args={[lineWidth, height]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <mesh position={[width / 2 - lineWidth / 2, 0, 0]}>
        <planeGeometry args={[lineWidth, height]} />
        <meshBasicMaterial color={color} />
      </mesh>
      
      {/* Corner accents */}
      <CornerAccents width={width} height={height} color={color} />
      
      {/* Label background */}
      <mesh position={[-width / 2 + 0.025, height / 2 + 0.006, 0.001]}>
        <planeGeometry args={[0.045, 0.010]} />
        <meshBasicMaterial color="#000000" transparent opacity={0.75} />
      </mesh>
      
      {/* Label text */}
      <Text
        position={[-width / 2 + 0.025, height / 2 + 0.006, 0.002]}
        fontSize={0.006}
        color={color}
        anchorX="center"
        anchorY="middle"
        maxWidth={0.1}
      >
        {label}
      </Text>
    </group>
  )
}

// ============================================================
// Main Component
// ============================================================

interface XRCameraFeedDisplayProps {
  state: XRCameraState
  texture: THREE.VideoTexture | null
  /** Face detections (cyan boxes) */
  detections?: FaceDetectionData[]
  /** Object detections from YOLO (colored boxes) */
  objectDetections?: Detection[]
  imageSize?: { width: number; height: number } | null
  /** Show the video feed behind overlays (default: false for overlay-only mode) */
  showVideo?: boolean
}

/**
 * XRCameraFeedDisplay - Renders face and object detection overlays in XR space
 * 
 * By default, only the bounding box overlays are visible (no video feed).
 * The overlay plane is positioned to align with real-world objects as seen
 * through Quest 3 passthrough.
 */
export function XRCameraFeedDisplay({
  state,
  texture,
  detections = [],
  objectDetections = [],
  imageSize = null,
  showVideo = false,
}: XRCameraFeedDisplayProps) {
  const session = useXR((s) => s.session)
  const isPresenting = !!session
  const { camera } = useThree()
  const groupRef = useRef<THREE.Group>(null)
  const materialRef = useRef<THREE.MeshBasicMaterial>(null)

  // Update texture when it changes
  useEffect(() => {
    if (materialRef.current && texture) {
      materialRef.current.map = texture
      materialRef.current.needsUpdate = true
    }
  }, [texture])

  // Calculate plane dimensions from camera aspect ratio
  const planeDimensions = useMemo(() => {
    if (state.width && state.height) {
      const aspectRatio = state.width / state.height
      const height = OVERLAY_CONFIG.planeHeight
      const width = height * aspectRatio
      return { width, height }
    }
    return { width: 0.27, height: 0.2 } // Default 4:3
  }, [state.width, state.height])

  // Position overlay to follow head (HUD-style)
  useFrame(() => {
    if (!groupRef.current || !isPresenting) return

    const cameraPosition = new THREE.Vector3()
    const cameraQuat = new THREE.Quaternion()
    camera.getWorldPosition(cameraPosition)
    camera.getWorldQuaternion(cameraQuat)

    // Calculate basis vectors in camera space
    const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(cameraQuat).normalize()
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(cameraQuat).normalize()
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(cameraQuat).normalize()

    // Position the overlay plane
    const position = cameraPosition.clone()
      .add(forward.multiplyScalar(OVERLAY_CONFIG.distance))
      .add(right.multiplyScalar(OVERLAY_CONFIG.xOffset))
      .add(up.multiplyScalar(OVERLAY_CONFIG.yOffset))

    groupRef.current.position.copy(position)
    groupRef.current.quaternion.copy(cameraQuat)

    // Scale to maintain apparent size at different distances
    const scale = OVERLAY_CONFIG.distance / OVERLAY_CONFIG.baseDistance
    groupRef.current.scale.setScalar(scale)
  })

  if (!isPresenting) return null

  return (
    <group ref={groupRef}>
      {/* Video plane (hidden by default) */}
      {showVideo && state.isStreaming && (
        <mesh>
          <planeGeometry args={[planeDimensions.width, planeDimensions.height]} />
          <meshBasicMaterial
            ref={materialRef}
            map={texture}
            side={THREE.DoubleSide}
            toneMapped={false}
            depthWrite={false}
          />
        </mesh>
      )}

      {/* Face detection bounding boxes (cyan) */}
      {state.isStreaming && imageSize && detections.map((detection) => (
        <BoundingBox
          key={`face-${detection.id}-${detection.bbox.x1}-${detection.bbox.y1}`}
          detection={detection}
          imageSize={imageSize}
          planeWidth={planeDimensions.width}
          planeHeight={planeDimensions.height}
        />
      ))}

      {/* Object detection bounding boxes (colored by class) */}
      {state.isStreaming && imageSize && objectDetections.map((detection) => (
        <ObjectBoundingBox
          key={`obj-${detection.id}-${detection.class}-${detection.bbox.x1}`}
          detection={detection}
          imageSize={imageSize}
          planeWidth={planeDimensions.width}
          planeHeight={planeDimensions.height}
        />
      ))}
    </group>
  )
}
