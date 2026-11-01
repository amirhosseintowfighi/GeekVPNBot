/**
 * The page behind every screen: near-black, one field of blue light rising
 * from the top corner, a lit arc at its edge, a vignette and a film of grain.
 *
 * Fixed and drawn once, under everything, so it never scrolls or repaints with
 * the content. The class name is what the classic (reseller) theme hides: our
 * light stays out of a shop that is not ours.
 */
export function SkyBackdrop() {
  return (
    <div aria-hidden className="sky-backdrop pointer-events-none fixed inset-0 overflow-hidden">
      <svg
        className="absolute inset-0 size-full"
        viewBox="0 0 390 844"
        preserveAspectRatio="xMidYMin slice"
      >
        <defs>
          <radialGradient id="sb-vignette" cx="0.5" cy="0.5" r="0.75">
            <stop offset="0.55" stopColor="#000" stopOpacity="0" />
            <stop offset="1" stopColor="#000" stopOpacity="0.55" />
          </radialGradient>
          <radialGradient id="sb-arc" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="#0A1A8C" />
            <stop offset="0.82" stopColor="#1238E8" />
            <stop offset="1" stopColor="#3D7BFF" />
          </radialGradient>
          <filter id="sb-wide" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="39" />
          </filter>
          <filter id="sb-mid" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="18" />
          </filter>
          <filter id="sb-edge" x="-10%" y="-10%" width="120%" height="120%">
            <feGaussianBlur stdDeviation="1.8" />
          </filter>
          <filter id="sb-grain" x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="5" stitchTiles="stitch" />
            <feColorMatrix
              type="matrix"
              values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 1.8 -0.62"
            />
          </filter>
        </defs>
        <rect width="390" height="844" fill="#02040E" />
        <ellipse cx="39" cy="211" rx="273" ry="380" fill="#0B2FD0" opacity="0.55" filter="url(#sb-wide)" />
        <circle cx="-47" cy="-42" r="316" fill="#1E5BFF" opacity="0.55" filter="url(#sb-mid)" />
        <circle cx="-47" cy="-42" r="304" fill="url(#sb-arc)" />
        <circle
          cx="-47"
          cy="-42"
          r="304"
          fill="none"
          stroke="#BFD8FF"
          strokeOpacity="0.85"
          strokeWidth="2.4"
          filter="url(#sb-edge)"
        />
        <rect width="390" height="844" fill="url(#sb-vignette)" />
        <rect width="390" height="844" filter="url(#sb-grain)" opacity="0.2" />
      </svg>
    </div>
  )
}
