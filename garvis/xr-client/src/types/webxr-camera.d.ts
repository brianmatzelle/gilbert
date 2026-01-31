/**
 * TypeScript declarations for WebXR extensions
 * 
 * Basic XR types are included in lib.dom.d.ts
 * These extend the standard types with additional properties we may use
 */

// Extend XRSession with enabledFeatures (may not be in all type defs)
interface XRSession {
  readonly enabledFeatures?: readonly string[]
}

export {}

