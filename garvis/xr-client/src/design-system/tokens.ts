/**
 * Design System Tokens
 * 
 * Centralized design tokens for the Garvis XR UI.
 * All colors, spacing, and typography values should be defined here.
 */

// ============================================================================
// COLORS
// ============================================================================

export const colors = {
  // Background colors
  bg: {
    primary: '#1a1a2e',      // Main window/panel background
    secondary: '#16213e',    // Secondary panels
    overlay: '#000000',      // Loading overlays
  },

  // Accent colors
  accent: {
    primary: '#6366f1',      // Indigo - buttons, borders
    primaryHover: '#818cf8', // Lighter indigo on hover
    secondary: '#60a5fa',    // Blue - titles, highlights
    secondaryHover: '#93c5fd', // Lighter blue on hover
  },

  // Semantic colors
  success: {
    base: '#22c55e',         // Green - active/success states
    hover: '#4ade80',
  },
  error: {
    base: '#ef4444',         // Red - errors, close buttons, muted
    hover: '#f87171',
  },
  warning: {
    base: '#fbbf24',         // Amber - warnings
    hover: '#fcd34d',
  },

  // Text colors
  text: {
    primary: '#ffffff',      // Main text
    secondary: '#888888',    // Muted text, labels
    tertiary: '#666666',     // Even more muted
    disabled: '#444444',     // Disabled states
    user: '#4ade80',         // User messages (green)
    assistant: '#60a5fa',    // Assistant messages (blue)
  },

  // Interactive element colors
  interactive: {
    default: '#888888',
    hover: '#60a5fa',
    active: '#ffffff',
    disabled: '#333333',
  },

  // Border colors
  border: {
    default: '#444444',
    accent: '#6366f1',
  },
} as const

// ============================================================================
// SPACING
// ============================================================================

export const spacing = {
  /** Extra small: 0.005 */
  xs: 0.005,
  /** Small: 0.01 */
  sm: 0.01,
  /** Medium: 0.02 */
  md: 0.02,
  /** Large: 0.03 */
  lg: 0.03,
  /** Extra large: 0.04 */
  xl: 0.04,
  /** 2x Extra large: 0.05 */
  '2xl': 0.05,
} as const

// ============================================================================
// TYPOGRAPHY
// ============================================================================

export const typography = {
  fontSize: {
    xs: 0.006,
    sm: 0.007,
    base: 0.008,
    md: 0.01,
    lg: 0.012,
    xl: 0.015,
    '2xl': 0.018,
    '3xl': 0.024,
  },
  lineHeight: {
    tight: 1.2,
    normal: 1.5,
    relaxed: 1.75,
  },
} as const

// ============================================================================
// RADII
// ============================================================================

export const radii = {
  sm: 0.002,
  md: 0.005,
  lg: 0.01,
  xl: 0.015,
} as const

// ============================================================================
// OPACITY
// ============================================================================

export const opacity = {
  /** Barely visible: 0.1 */
  subtle: 0.1,
  /** Glass effect: 0.12 */
  glass: 0.12,
  /** Light overlay: 0.2 */
  light: 0.2,
  /** Medium: 0.3 */
  medium: 0.3,
  /** Semi-transparent: 0.5 */
  semi: 0.5,
  /** Heavy overlay: 0.8 */
  heavy: 0.8,
  /** Almost opaque: 0.9 */
  strong: 0.9,
  /** Solid: 0.95 */
  solid: 0.95,
} as const

// ============================================================================
// ANIMATION
// ============================================================================

export const animation = {
  /** Smooth lerp factor for position/rotation */
  lerpFactor: 0.15,
  /** Fast lerp for responsive interactions */
  lerpFast: 0.25,
} as const

// ============================================================================
// Z-LAYERS (depth offsets in 3D space)
// ============================================================================

export const zLayers = {
  background: -0.003,
  border: -0.002,
  content: 0,
  overlay: 0.001,
  controls: 0.002,
  tooltip: 0.003,
  modal: 0.004,
} as const

// ============================================================================
// WINDOW DEFAULTS
// ============================================================================

export const windowDefaults = {
  titleBarHeight: 0.04,
  padding: 0.02,
  resizeHandleSize: 0.025,
  closeButtonWidth: 0.04,
  closeButtonHeight: 0.025,
  minScale: 0.5,
  maxScale: 2.0,
} as const

