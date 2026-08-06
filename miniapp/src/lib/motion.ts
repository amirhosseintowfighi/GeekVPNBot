/**
 * Shared Framer Motion presets.
 *
 * Centralised so that motion feels like one system rather than a dozen
 * separate opinions. Three rules are baked in:
 *
 * 1. **Short.** Nothing runs longer than 300ms. Inside a webview the customer
 *    is usually one tap deep into a task; animation should acknowledge the
 *    tap, not delay it.
 * 2. **Directional.** Enter transitions travel along the reading direction.
 *    In RTL that means forward navigation slides in from the left, which is
 *    the opposite of the LTR default and the detail most ports get wrong.
 * 3. **Opt-out.** `prefers-reduced-motion` is handled globally in CSS, and
 *    `MotionConfig` in the provider passes the same signal to Framer.
 */

import type { Transition, Variants } from 'framer-motion'

/** The house easing curve: quick out, soft landing. */
export const EASE = [0.22, 1, 0.36, 1] as const

export const springy: Transition = {
  type: 'spring',
  stiffness: 380,
  damping: 30,
  mass: 0.8,
}

export const quick: Transition = { duration: 0.22, ease: EASE }

/** Page-level enter. Paired with AnimatePresence in the shell. */
export const pageVariants: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: quick },
  exit: { opacity: 0, y: -8, transition: { duration: 0.15, ease: EASE } },
}

/**
 * Staggered list entry.
 *
 * The stagger is capped by `staggerChildren` being small: with 20 plans on
 * screen a 0.1s stagger would take two seconds to finish, which stops being
 * elegant and starts being slow.
 */
export const listVariants: Variants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.04, delayChildren: 0.02 },
  },
}

export const itemVariants: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: quick },
}

/** Bottom sheets and dialogs. */
export const sheetVariants: Variants = {
  hidden: { opacity: 0, y: 24, scale: 0.98 },
  visible: { opacity: 1, y: 0, scale: 1, transition: springy },
  exit: { opacity: 0, y: 16, scale: 0.98, transition: { duration: 0.15 } },
}

/** Numbers that change in place, such as a wallet balance after a top-up. */
export const countVariants: Variants = {
  hidden: { opacity: 0, y: 6 },
  visible: { opacity: 1, y: 0, transition: quick },
  exit: { opacity: 0, y: -6, transition: { duration: 0.12 } },
}

/** A single attention pulse. Used once, on a successful purchase. */
export const successPulse: Variants = {
  hidden: { scale: 0.9, opacity: 0 },
  visible: {
    scale: [0.9, 1.04, 1],
    opacity: 1,
    transition: { duration: 0.45, ease: EASE, times: [0, 0.6, 1] },
  },
}
