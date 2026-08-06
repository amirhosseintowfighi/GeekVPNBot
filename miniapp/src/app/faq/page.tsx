'use client'

import useSWR from 'swr'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Card } from '@/components/ui/card'
import { SkeletonList } from '@/components/ui/skeleton'
import { ApiError, fetcher } from '@/lib/api'
import type { FaqSection } from '@/lib/types'

/**
 * FAQ.
 *
 * The content is fetched rather than bundled, even though it changes rarely.
 * The bot serves the same `faq_content` module, and duplicating the copy here
 * would guarantee that one of the two eventually answers a billing question
 * differently from the other.
 *
 * `type="multiple"` because people comparing two answers should not have the
 * first one close when they open the second.
 */
export default function FaqPage() {
  const { data, error, mutate } = useSWR<FaqSection[]>(
    '/api/miniapp/faq',
    fetcher,
  )

  return (
    <>
      <PageHeader
        title={'\u0633\u0648\u0627\u0644\u0627\u062a \u0645\u062a\u062f\u0627\u0648\u0644'}
      />

      {error instanceof ApiError && !data ? (
        <ErrorState
          messageFa={error.messageFa}
          offline={error.status === 0}
          onRetry={() => void mutate()}
        />
      ) : !data ? (
        <SkeletonList count={3} />
      ) : data.length === 0 ? (
        <EmptyState
          title={'\u0645\u062d\u062a\u0648\u0627\u06cc\u06cc \u062f\u0631 \u062f\u0633\u062a\u0631\u0633 \u0646\u06cc\u0633\u062a'}
        />
      ) : (
        <div className="space-y-4 pb-4">
          {data.map((section) => (
            <Card key={section.key} className="px-4 py-2">
              <h2 className="flex items-center gap-2 py-2 text-sm font-semibold">
                {section.icon ? <span aria-hidden>{section.icon}</span> : null}
                {section.titleFa}
              </h2>

              <Accordion type="multiple">
                {section.entries.map((entry) => (
                  <AccordionItem key={entry.key} value={entry.key}>
                    <AccordionTrigger>{entry.questionFa}</AccordionTrigger>
                    <AccordionContent>
                      <p className="whitespace-pre-wrap">{entry.answerFa}</p>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
