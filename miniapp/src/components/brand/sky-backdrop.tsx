/**
 * The page behind every screen: deep navy with soft fields of light - a cool
 * blue rising on the left, violet in the upper corner, the bottom falling to
 * black - under a vignette and a film of grain. The glass panes on top are
 * frosted, so what they show is this light, softened.
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
          <linearGradient id="sb-ground" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#0B1660" />
            <stop offset="0.5" stopColor="#060B34" />
            <stop offset="1" stopColor="#02030C" />
          </linearGradient>
          <radialGradient id="sb-vignette" cx="0.5" cy="0.45" r="0.8">
            <stop offset="0.5" stopColor="#000" stopOpacity="0" />
            <stop offset="1" stopColor="#000" stopOpacity="0.6" />
          </radialGradient>
          <filter id="sb-soft" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="60" />
          </filter>
          <filter id="sb-grain" x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="5" stitchTiles="stitch" />
            <feColorMatrix
              type="matrix"
              values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 1.8 -0.62"
            />
          </filter>
        </defs>
        <rect width="390" height="844" fill="url(#sb-ground)" />
        {/* A wide blue field, the body of the light. */}
        <ellipse cx="120" cy="300" rx="260" ry="300" fill="#1D3BFF" opacity="0.55" filter="url(#sb-soft)" />
        {/* Its bright cool edge on the left, as in the poster. */}
        <ellipse cx="-30" cy="430" rx="120" ry="230" fill="#3FA2E8" opacity="0.55" filter="url(#sb-soft)" />
        {/* Violet in the upper corner. */}
        <ellipse cx="380" cy="40" rx="190" ry="160" fill="#7B3FF2" opacity="0.55" filter="url(#sb-soft)" />
        {/* A low violet ember, so the bottom of a long page is not dead black. */}
        <ellipse cx="300" cy="820" rx="200" ry="120" fill="#4A2BD8" opacity="0.35" filter="url(#sb-soft)" />
        <rect width="390" height="844" fill="url(#sb-vignette)" />
        <rect width="390" height="844" filter="url(#sb-grain)" opacity="0.16" />
      </svg>
    </div>
  )
}
