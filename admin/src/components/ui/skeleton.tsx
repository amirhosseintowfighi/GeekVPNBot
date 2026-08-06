import { cn } from '@/lib/utils'

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />
}

/**
 * A skeleton shaped like the table it replaces.
 *
 * The row count and height match the real table, so the page does not jump
 * when data lands. A generic spinner would be less work and a worse
 * experience: the operator's eye has already settled where the first row will
 * appear.
 */
function SkeletonTable({ rows = 8, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="divide-y divide-border" aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex h-10 items-center gap-3 px-3">
          {Array.from({ length: cols }).map((__, colIndex) => (
            <Skeleton
              key={colIndex}
              className={cn('h-3', colIndex === 0 ? 'w-40' : 'w-20')}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

function SkeletonCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="surface space-y-3 p-4">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-2 w-16" />
        </div>
      ))}
    </div>
  )
}

function SkeletonChart({ className }: { className?: string }) {
  return <Skeleton className={cn('h-64 w-full', className)} />
}

export { Skeleton, SkeletonTable, SkeletonCards, SkeletonChart }
