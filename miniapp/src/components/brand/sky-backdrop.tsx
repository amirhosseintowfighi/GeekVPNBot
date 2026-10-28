import { Logo } from '@/components/brand/logo'

/**
 * The page behind everything: the logo-blue glows and the faint concentric
 * rings of the Sky Lens design, plus the mark as a watermark.
 *
 * Fixed and inert - it never scrolls, never takes a tap and is hidden from
 * assistive technology. Drawn with SVG rather than stacked gradients so the
 * rings stay one hairline wide at any device pixel ratio.
 */
export function SkyBackdrop() {
  const rings = [120, 200, 280, 360, 440, 520]
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 overflow-hidden">
      <svg
        className="absolute inset-0 size-full"
        viewBox="0 0 390 844"
        preserveAspectRatio="xMidYMid slice"
      >
        <circle cx="39" cy="776" r="260" fill="rgba(0,172,254,0.55)" />
        <circle cx="331" cy="160" r="190" fill="rgba(0,172,254,0.45)" />
        {rings.map((r, i) => (
          <circle
            key={r}
            cx="331"
            cy="160"
            r={r}
            fill="none"
            stroke="white"
            strokeOpacity={0.1 - i * 0.014}
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      <Logo className="absolute -left-28 bottom-36 w-[351px] text-white opacity-[0.06]" />
    </div>
  )
}
