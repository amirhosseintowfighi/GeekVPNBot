import { cn } from '@/lib/utils'

/**
 * Loading placeholder.
 *
 * A shimmer rather than a spinner: skeletons that match the shape of the
 * content make the wait feel shorter and stop the layout jumping when data
 * lands. The sweep runs right-to-left to match the reading direction.
 */
function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-md bg-muted/70',
        'after:absolute after:inset-0 after:-translate-x-full after:animate-shimmer',
        'after:bg-gradient-to-l after:from-transparent after:via-white/5 after:to-transparent',
        className,
      )}
      aria-hidden
      {...props}
    />
  )
}

/** The repeated card skeleton used by the shop, wallet, and support lists. */
function SkeletonCard() {
  return (
    <div className="surface space-y-3 p-4">
      <Skeleton className="h-5 w-2/5" />
      <Skeleton className="h-4 w-4/5" />
      <Skeleton className="h-9 w-full" />
    </div>
  )
}

function SkeletonList({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }, (_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  )
}

export { Skeleton, SkeletonCard, SkeletonList }
