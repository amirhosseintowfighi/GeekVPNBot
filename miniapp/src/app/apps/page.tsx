'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Download, Monitor, Smartphone } from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SkeletonList } from '@/components/ui/skeleton'
import { ApiError, fetcher } from '@/lib/api'
import { plainText } from '@/lib/fa'
import { haptic, openLink } from '@/lib/telegram'
import type { AppDownload, AppsScreen } from '@/lib/types'

const PLATFORM_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  android: Smartphone,
  windows: Monitor,
}

/**
 * The Geek apps and how to connect - the bot's "دانلود و آموزش", as a page.
 *
 * The links are the latest release of each app, the same files the apps'
 * own updaters fetch, so this page never offers a version the app would
 * immediately ask to replace.
 */
export default function AppsPage() {
  const { data, error, mutate } = useSWR<AppsScreen>('/api/miniapp/apps', fetcher)

  return (
    <>
      <PageHeader title={'دانلود و آموزش'} subtitle={'برنامه‌های گیک و آموزش اتصال'} />

      {error instanceof ApiError && !data ? (
        <ErrorState messageFa={error.messageFa} offline={error.status === 0} onRetry={() => void mutate()} />
      ) : !data ? (
        <SkeletonList count={3} />
      ) : data.downloads.length === 0 && data.tutorials.length === 0 ? (
        <EmptyState
          title={'هنوز چیزی اضافه نشده'}
          description={'اگه برای اتصال کمک لازم داری، به پشتیبانی پیام بده.'}
        />
      ) : (
        <div className="space-y-4 pb-4">
          {data.downloads.length > 0 ? (
            <section className="space-y-3">
              <h2 className="section-label">{'دانلود برنامه'}</h2>
              {data.downloads.map((download) => (
                <DownloadCard key={download.platform} download={download} />
              ))}
            </section>
          ) : null}

          {data.tutorials.length > 0 ? (
            <section className="space-y-3">
              <h2 className="section-label">{'آموزش اتصال'}</h2>
              <Card className="px-4 py-2">
                <Accordion type="multiple">
                  {data.tutorials.map((tutorial) => (
                    <AccordionItem key={tutorial.device} value={tutorial.device}>
                      <AccordionTrigger>{tutorial.labelFa}</AccordionTrigger>
                      <AccordionContent>
                        {tutorial.textFa ? (
                          <p className="whitespace-pre-line text-sm leading-loose">
                            {plainText(tutorial.textFa)}
                          </p>
                        ) : null}
                        {tutorial.kind !== 'text' ? (
                          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                            {tutorial.kind === 'video'
                              ? 'ویدیوی این آموزش در ربات است: «دانلود و آموزش» را در ربات بزنید.'
                              : 'تصویر این آموزش در ربات است: «دانلود و آموزش» را در ربات بزنید.'}
                          </p>
                        ) : null}
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </Card>
            </section>
          ) : null}
        </div>
      )}
    </>
  )
}

function DownloadCard({ download }: { download: AppDownload }) {
  const Icon = PLATFORM_ICON[download.platform] ?? Download
  return (
    <Card className="flex items-center gap-3 p-4">
      <span className="icon-tile size-12 rounded-2xl" aria-hidden>
        <Icon className="size-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-base font-extrabold">{download.labelFa}</p>
        <p className="nums mt-0.5 text-xs text-muted-foreground" dir="auto">
          {download.version ? `نسخهٔ ${download.version}` : 'آخرین نسخه'}
        </p>
      </div>
      <Button
        size="sm"
        onClick={() => {
          haptic.impact('light')
          openLink(download.url)
        }}
      >
        <Download className="size-4" aria-hidden />
        {'دانلود'}
      </Button>
    </Card>
  )
}
