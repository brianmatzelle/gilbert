import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Text } from '@react-three/drei'
import * as THREE from 'three'

export interface BoundingBox {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface FaceDetectionData {
  id: number
  confidence: number
  bbox: BoundingBox
  center?: { x: number; y: number }
  searchState: 'idle' | 'searching' | 'found' | 'not_found'
  personName?: string | null
}

interface FaceBoundingBoxProps {
  detection: FaceDetectionData
  imageSize: { width: number; height: number }
  cameraPos: THREE.Vector3
  cameraDir: THREE.Vector3
}

// Cyan color scheme for face detection
const COLORS = {
  idle: '#00ffff',      // Cyan - default face box
  searching: '#f59e0b', // Amber - searching animation
  found: '#22c55e',     // Green - person identified
  not_found: '#ef4444', // Red - no match found
}

/**
 * FaceBoundingBox - Animated bounding box for detected faces
 * 
 * Features:
 * - Cyan-colored frame with corner accents
 * - Spinning dashed border animation when searching
 * - Pulsing glow effect
 * - Smooth position transitions
 */
export function FaceBoundingBox({ 
  detection, 
  imageSize, 
  cameraPos, 
  cameraDir 
}: FaceBoundingBoxProps) {
  const groupRef = useRef<THREE.Group>(null)
  const spinnerRef = useRef<THREE.Group>(null)
  const timeRef = useRef(0)
  
  const { searchState, confidence, personName } = detection
  const isSearching = searchState === 'searching'
  const color = COLORS[searchState] || COLORS.idle
  
  // Calculate 3D position from 2D bounding box
  const position = useMemo(() => {
    const { bbox } = detection
    const centerX = (bbox.x1 + bbox.x2) / 2
    const centerY = (bbox.y1 + bbox.y2) / 2
    
    // Normalize to -1 to 1 range (center of image = 0,0)
    const normalizedX = (centerX / imageSize.width) * 2 - 1
    const normalizedY = -((centerY / imageSize.height) * 2 - 1) // Flip Y
    
    const horizontalSpread = 0.5
    const verticalSpread = 0.4
    const distance = 0.55
    
    // Calculate horizontal direction (perpendicular to camera)
    const horizontalRight = new THREE.Vector3(-cameraDir.z, 0, cameraDir.x).normalize()
    
    // Position in front of camera
    const pos = cameraPos.clone()
      .add(cameraDir.clone().multiplyScalar(distance))
      .add(horizontalRight.multiplyScalar(normalizedX * horizontalSpread))
      .add(new THREE.Vector3(0, normalizedY * verticalSpread, 0))
    
    return pos
  }, [detection, imageSize, cameraPos, cameraDir])

  // Calculate box size based on face size
  const boxSize = useMemo(() => {
    const { bbox } = detection
    const faceWidth = bbox.x2 - bbox.x1
    const faceHeight = bbox.y2 - bbox.y1
    
    // Scale factor to convert image pixels to 3D units
    const scaleFactor = 0.0003
    
    return {
      width: Math.max(0.04, faceWidth * scaleFactor),
      height: Math.max(0.05, faceHeight * scaleFactor)
    }
  }, [detection])

  // Animation frame
  useFrame((_, delta) => {
    timeRef.current += delta
    
    // Face camera
    if (groupRef.current) {
      groupRef.current.lookAt(cameraPos)
    }
    
    // Spin the dashed border when searching
    if (spinnerRef.current && isSearching) {
      spinnerRef.current.rotation.z = timeRef.current * 2
    }
  })

  const cornerSize = Math.min(boxSize.width, boxSize.height) * 0.25
  const labelText = searchState === 'found' && personName 
    ? personName 
    : searchState === 'searching' 
      ? 'Searching...' 
      : `${Math.round(confidence * 100)}%`

  return (
    <group ref={groupRef} position={position}>
      {/* Main bounding box frame */}
      <group>
        {/* Corner accents - Top Left */}
        <CornerAccent 
          position={[-boxSize.width/2, boxSize.height/2, 0]} 
          rotation={0}
          size={cornerSize}
          color={color}
        />
        {/* Corner accents - Top Right */}
        <CornerAccent 
          position={[boxSize.width/2, boxSize.height/2, 0]} 
          rotation={Math.PI/2}
          size={cornerSize}
          color={color}
        />
        {/* Corner accents - Bottom Right */}
        <CornerAccent 
          position={[boxSize.width/2, -boxSize.height/2, 0]} 
          rotation={Math.PI}
          size={cornerSize}
          color={color}
        />
        {/* Corner accents - Bottom Left */}
        <CornerAccent 
          position={[-boxSize.width/2, -boxSize.height/2, 0]} 
          rotation={-Math.PI/2}
          size={cornerSize}
          color={color}
        />
      </group>

      {/* Spinning dashed border (when searching) */}
      {isSearching && (
        <group ref={spinnerRef}>
          <DashedBorder 
            width={boxSize.width * 1.1} 
            height={boxSize.height * 1.1}
            color={COLORS.searching}
          />
        </group>
      )}

      {/* Pulsing glow effect (when searching) */}
      {isSearching && (
        <PulsingGlow 
          width={boxSize.width} 
          height={boxSize.height}
          time={timeRef.current}
        />
      )}

      {/* Label below the box */}
      <group position={[0, -boxSize.height/2 - 0.015, 0]}>
        {/* Background pill */}
        <mesh position={[0, 0, -0.001]}>
          <planeGeometry args={[0.06, 0.015]} />
          <meshBasicMaterial color="#000000" transparent opacity={0.8} />
        </mesh>
        
        {/* Label text */}
        <Text
          fontSize={0.008}
          color={color}
          anchorX="center"
          anchorY="middle"
          outlineWidth={0.0005}
          outlineColor="#000000"
        >
          {labelText}
        </Text>

        {/* Status icon */}
        {isSearching && (
          <Text
            position={[-0.025, 0, 0]}
            fontSize={0.008}
            color={COLORS.searching}
            anchorX="center"
            anchorY="middle"
          >
            🔍
          </Text>
        )}
      </group>
    </group>
  )
}

/**
 * Corner accent - L-shaped corner indicator
 */
function CornerAccent({ 
  position, 
  rotation, 
  size, 
  color 
}: { 
  position: [number, number, number]
  rotation: number
  size: number
  color: string 
}) {
  const thickness = 0.0008
  return (
    <group position={position} rotation={[0, 0, rotation]}>
      {/* Horizontal line */}
      <mesh position={[size/2, 0, 0]}>
        <planeGeometry args={[size, thickness]} />
        <meshBasicMaterial color={color} />
      </mesh>
      {/* Vertical line */}
      <mesh position={[0, -size/2, 0]}>
        <planeGeometry args={[thickness, size]} />
        <meshBasicMaterial color={color} />
      </mesh>
    </group>
  )
}

/**
 * Dashed border that rotates when searching
 */
function DashedBorder({ 
  width, 
  height, 
  color 
}: { 
  width: number
  height: number
  color: string 
}) {
  const dashCount = 12
  const dashLength = (2 * (width + height)) / dashCount / 2
  
  // Create dash positions around the rectangle
  const dashes = useMemo(() => {
    const positions: { x: number; y: number; rotation: number }[] = []
    const perimeter = 2 * (width + height)
    const spacing = perimeter / dashCount
    
    for (let i = 0; i < dashCount; i++) {
      const dist = i * spacing
      let x = 0, y = 0, rot = 0
      
      if (dist < width) {
        // Top edge
        x = -width/2 + dist
        y = height/2
        rot = 0
      } else if (dist < width + height) {
        // Right edge
        x = width/2
        y = height/2 - (dist - width)
        rot = Math.PI/2
      } else if (dist < 2*width + height) {
        // Bottom edge
        x = width/2 - (dist - width - height)
        y = -height/2
        rot = 0
      } else {
        // Left edge
        x = -width/2
        y = -height/2 + (dist - 2*width - height)
        rot = Math.PI/2
      }
      
      positions.push({ x, y, rotation: rot })
    }
    
    return positions
  }, [width, height, dashCount])

  return (
    <group>
      {dashes.map((dash, i) => (
        <mesh 
          key={i} 
          position={[dash.x, dash.y, 0.001]}
          rotation={[0, 0, dash.rotation]}
        >
          <planeGeometry args={[dashLength * 0.6, 0.0007]} />
          <meshBasicMaterial color={color} transparent opacity={0.8} />
        </mesh>
      ))}
    </group>
  )
}

/**
 * Pulsing glow effect behind the box
 */
function PulsingGlow({ 
  width, 
  height, 
  time 
}: { 
  width: number
  height: number
  time: number 
}) {
  // Pulse between 0.2 and 0.5 opacity
  const opacity = 0.2 + Math.sin(time * 4) * 0.15
  
  return (
    <mesh position={[0, 0, -0.002]}>
      <planeGeometry args={[width * 1.3, height * 1.3]} />
      <meshBasicMaterial 
        color={COLORS.searching} 
        transparent 
        opacity={opacity}
      />
    </mesh>
  )
}

