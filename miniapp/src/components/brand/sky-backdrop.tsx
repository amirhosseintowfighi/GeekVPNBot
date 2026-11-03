'use client'

import { usePathname } from 'next/navigation'

/**
 * The page behind every screen, drawn as in the client design: near-black
 * ground, one large shape of blue light per screen, a vignette and a film of
 * grain. The glass panes on top are frosted, so what they show is this light,
 * softened.
 *
 * Each section of the app has its own light, the way each screen of the design
 * does, so moving between tabs reads as moving between places rather than
 * scrolling one long page. Geometry is copied from the design's 390×844
 * artboards and scaled to cover; anchored at the top so the shape sits where
 * the design put it on any phone height.
 *
 * Fixed and drawn once, under everything, so it never scrolls or repaints with
 * the content. The class name is what the classic (reseller) theme hides: our
 * light stays out of a shop that is not ours.
 */

type Scene = 'planet' | 'ribbon' | 'pool' | 'columns' | 'horizon' | 'beam'

/** Longest prefix wins, so /wallet/topup keeps the wallet's light. */
const SCENES: ReadonlyArray<readonly [string, Scene]> = [
  ['/services', 'pool'],
  ['/shop', 'planet'],
  ['/wallet', 'planet'],
  ['/payments', 'columns'],
  ['/profile', 'columns'],
  ['/settings', 'columns'],
  ['/referral', 'columns'],
  ['/status', 'horizon'],
  ['/support', 'ribbon'],
  ['/faq', 'ribbon'],
  ['/apps', 'beam'],
]

function sceneFor(pathname: string): Scene {
  if (pathname === '/') return 'planet'
  const hit = SCENES.find(([prefix]) => pathname === prefix || pathname.startsWith(`${prefix}/`))
  return hit ? hit[1] : 'ribbon'
}

/* The design's light columns: widths and fade, left to right. */
const COLUMNS: ReadonlyArray<readonly [number, number, number]> = [
  [0, 16, 0.95],
  [15, 30, 0.89],
  [43, 29, 0.78],
  [69, 19, 0.68],
  [86, 23, 0.61],
  [108, 22, 0.52],
  [128, 26, 0.44],
  [152, 29, 0.34],
  [179, 15, 0.24],
  [193, 14, 0.18],
  [206, 30, 0.13],
  [234, 22, 0.02],
]

/* The beam: one disc repeated down the page, fading as it falls. */
const BEAM: ReadonlyArray<readonly [number, number]> = [
  [421, 0.06], [398, 0.061], [375, 0.065], [352, 0.073], [329, 0.084], [305, 0.099],
  [282, 0.118], [259, 0.141], [236, 0.169], [213, 0.201], [190, 0.238], [166, 0.279],
  [143, 0.326], [120, 0.377], [97, 0.433], [74, 0.494], [51, 0.56],
]

function Light({ scene }: { scene: Scene }) {
  switch (scene) {
    case 'planet':
      // A planet rising from the top corner, its rim lit.
      return (
        <>
          <ellipse cx="39" cy="211" rx="273" ry="380" fill="#0B2FD0" opacity="0.55" filter="url(#sb-f1)" />
          <circle cx="-47" cy="-42" r="316" fill="#1E5BFF" opacity="0.55" filter="url(#sb-f2)" />
          <circle cx="-47" cy="-42" r="304" fill="url(#sb-arc)" />
          <circle
            cx="-47"
            cy="-42"
            r="304"
            fill="none"
            stroke="#BFD8FF"
            strokeOpacity="0.85"
            strokeWidth="2.4"
            filter="url(#sb-f4)"
          />
        </>
      )
    case 'ribbon':
      // A ribbon of light falling down the page.
      return (
        <>
          <path
            d="M0 -42 C215 211 -39 523 176 886"
            fill="none"
            stroke="#1F6FE0"
            strokeWidth="125"
            opacity="0.75"
            filter="url(#sb-f1)"
          />
          <path
            d="M0 -42 C215 211 -39 523 176 886"
            fill="none"
            stroke="#4FA2FF"
            strokeWidth="31"
            opacity="0.45"
            filter="url(#sb-f2)"
          />
        </>
      )
    case 'pool':
      // A pool of light low on the leading edge.
      return (
        <>
          <path
            d="M169 523 C169 564 186 626 159 658 C133 690 57 720 12 715 C-32 709 -95 669 -107 626 C-118 584 -78 509 -60 460 C-41 411 -31 342 5 334 C42 326 132 381 159 412 C187 444 169 482 169 523Z"
            fill="#3FB8FF"
            opacity="0.65"
            filter="url(#sb-f1)"
          />
          <path
            d="M168 506 C169 548 140 639 116 657 C91 675 45 627 22 613 C-0 599 -4 602 -21 574 C-38 546 -88 480 -79 445 C-70 410 2 371 33 365 C64 359 84 384 107 407 C129 431 166 465 168 506Z"
            fill="#1424D8"
            opacity="0.95"
            filter="url(#sb-f2)"
          />
          <ellipse cx="20" cy="464" rx="47" ry="68" fill="#06106A" opacity="0.9" filter="url(#sb-f2)" />
        </>
      )
    case 'columns':
      // Columns of light, brightest at the edge, with a glow at their foot.
      return (
        <>
          {COLUMNS.map(([x, w, o]) => (
            <rect key={x} x={x} y="0" width={w} height="844" fill="url(#sb-bar)" opacity={o} filter="url(#sb-fx)" />
          ))}
          <ellipse cx="78" cy="844" rx="176" ry="186" fill="#BFE4FF" opacity="0.45" filter="url(#sb-f2)" />
        </>
      )
    case 'horizon':
      // A horizon curving up from the bottom corner.
      return (
        <>
          <ellipse cx="20" cy="802" rx="215" ry="253" fill="#1E5FD6" opacity="0.9" filter="url(#sb-f1)" />
          <ellipse cx="0" cy="844" rx="117" ry="135" fill="#9CD8FF" opacity="0.85" filter="url(#sb-f2)" />
          <ellipse cx="215" cy="127" rx="234" ry="211" fill="#0A1F7A" opacity="0.55" filter="url(#sb-f1)" />
          <path d="M-20 861 C98 675 215 464 429 304 L429 1013 L-20 1013Z" fill="#061650" opacity="0.65" filter="url(#sb-f2)" />
          <path
            d="M-20 861 C98 675 215 464 429 304"
            fill="none"
            stroke="#3E8BFF"
            strokeOpacity="0.55"
            strokeWidth="23"
            filter="url(#sb-f3)"
          />
          <path
            d="M-20 861 C98 675 215 464 429 304"
            fill="none"
            stroke="#D6F1FF"
            strokeOpacity="0.9"
            strokeWidth="2.4"
            filter="url(#sb-f4)"
          />
        </>
      )
    case 'beam':
      // A beam of light from above, as on the sign-in screen.
      return (
        <>
          {BEAM.map(([cy, o]) => (
            <circle key={cy} cx="195" cy={cy} r="105" fill="#1A2FFF" opacity={o} />
          ))}
          <ellipse cx="195" cy="93" rx="136" ry="152" fill="#1A2FFF" opacity="0.35" filter="url(#sb-f1)" />
        </>
      )
  }
}

export function SkyBackdrop() {
  const scene = sceneFor(usePathname() ?? '/')

  return (
    <div aria-hidden className="sky-backdrop pointer-events-none fixed inset-0 overflow-hidden">
      <svg className="absolute inset-0 size-full" viewBox="0 0 390 844" preserveAspectRatio="xMidYMin slice">
        <defs>
          <radialGradient id="sb-vignette" cx="0.5" cy="0.5" r="0.75">
            <stop offset="0.55" stopColor="#000" stopOpacity="0" />
            <stop offset="1" stopColor="#000" stopOpacity="0.55" />
          </radialGradient>
          <filter id="sb-f1" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="39" />
          </filter>
          <filter id="sb-f2" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="18" />
          </filter>
          <filter id="sb-f3" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="5" />
          </filter>
          <filter id="sb-f4" x="-10%" y="-10%" width="120%" height="120%">
            <feGaussianBlur stdDeviation="1.8" />
          </filter>
          <filter id="sb-fx" x="-10%" y="0" width="120%" height="100%">
            <feGaussianBlur stdDeviation="5 0" />
          </filter>
          <filter id="sb-grain" x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="5" stitchTiles="stitch" />
            <feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 1.8 -0.62" />
          </filter>
          <linearGradient id="sb-bar" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#0B2A7A" stopOpacity="0" />
            <stop offset="0.45" stopColor="#2F7FD8" stopOpacity="0.55" />
            <stop offset="1" stopColor="#CDEBFF" />
          </linearGradient>
          <radialGradient id="sb-arc" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="#0A1A8C" />
            <stop offset="0.82" stopColor="#1238E8" />
            <stop offset="1" stopColor="#3D7BFF" />
          </radialGradient>
        </defs>
        <rect width="390" height="844" fill="#02040E" />
        {/* Keyed by scene so a tab change fades the new light in rather than
            snapping the old shape into the new one. */}
        <g key={scene} className="sky-scene">
          <Light scene={scene} />
        </g>
        <rect width="390" height="844" fill="url(#sb-vignette)" />
        <rect width="390" height="844" filter="url(#sb-grain)" opacity="0.2" />
      </svg>
    </div>
  )
}
