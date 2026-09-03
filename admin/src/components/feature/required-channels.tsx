'use client'

import * as React from 'react'
import useSWR from 'swr'

import { ApiError, api } from '@/lib/api'
import type { RequiredChannelRow } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'

/**
 * Channels a customer must join before the bot serves them.
 *
 * One component for both panels. The platform's own list and a reseller's are
 * the same screen; only the routes differ, and those are picked by `scope`
 * rather than by a shop id in a URL - the API takes the shop from the token,
 * so there is nothing here that could point at somebody else's gate.
 */
export function RequiredChannels({ scope }: { scope: 'platform' | 'mine' }) {
  const routes = scope === 'mine' ? MINE : PLATFORM
  const { data, mutate } = useSWR<RequiredChannelRow[]>(['channels', scope], routes.list)

  const [chatRef, setChatRef] = React.useState('')
  const [titleFa, setTitleFa] = React.useState('')
  const [inviteUrl, setInviteUrl] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await work()
      await mutate()
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'انجام نشد.')
    } finally {
      setBusy(false)
    }
  }

  const ref = chatRef.trim()
  const isPrivate = ref.length > 0 && !ref.startsWith('@')
  // The API refuses this too. Saying so here means the operator finds out
  // while they are still looking at the field rather than after a round trip.
  const needsInvite = isPrivate && inviteUrl.trim().length === 0
  const canAdd = ref.length > 0 && titleFa.trim().length > 0 && !needsInvite && !busy

  return (
    <Card className="space-y-4 p-4">
      <div>
        <div className="text-sm font-medium">عضویت اجباری در کانال</div>
        <p className="mt-1 text-2xs text-muted-foreground">
          تا وقتی کاربر عضو همهٔ کانال‌های فعال نشده باشد، ربات به او سرویس
          نمی‌دهد. اگر هیچ کانالی اضافه نکنید، هیچ اجباری در کار نیست.
        </p>
        <p className="mt-1 text-2xs text-warning">
          ربات باید در آن کانال ادمین باشد، وگرنه نمی‌تواند عضویت را بررسی کند —
          و کانالی که قابل بررسی نباشد نادیده گرفته می‌شود تا کسی پشت در نماند.
        </p>
      </div>

      {error ? <p className="text-2xs text-destructive">{error}</p> : null}

      {!data?.length ? (
        <p className="text-2xs text-muted-foreground">هنوز کانالی اضافه نشده.</p>
      ) : (
        <div className="divide-y rounded-md border text-2xs">
          {data.map((channel) => (
            <div key={channel.id} className="flex items-center justify-between gap-3 p-2">
              <div className="min-w-0">
                <div className="font-medium">{channel.titleFa}</div>
                <code dir="ltr" className="block break-all text-muted-foreground">
                  {channel.chatRef}
                </code>
                {channel.inviteUrl ? (
                  <code dir="ltr" className="block break-all text-muted-foreground/60">
                    {channel.inviteUrl}
                  </code>
                ) : null}
              </div>

              <div className="flex shrink-0 items-center gap-2">
                {channel.active ? (
                  <Badge variant="success">فعال</Badge>
                ) : (
                  <Badge variant="muted">غیرفعال</Badge>
                )}
                <Switch
                  checked={channel.active}
                  disabled={busy}
                  onCheckedChange={(next) =>
                    void run(() => routes.setActive(channel.id, next))
                  }
                />
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      if (!window.confirm(CONFIRM_REMOVE)) return
                      await routes.remove(channel.id)
                    })
                  }
                >
                  {'حذف'}
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-3 rounded-md border p-3">
        <div className="text-2xs font-medium">افزودن کانال</div>

        <Field label="شناسه" hint="کانال عمومی: @channelname — کانال خصوصی: شناسهٔ عددی مثل ‎-1001234567890">
          <Input
            dir="ltr"
            value={chatRef}
            onChange={(event) => setChatRef(event.target.value)}
            placeholder="@geekvpn"
          />
        </Field>

        <Field label="نامی که به کاربر نشان داده می‌شود">
          <Input
            value={titleFa}
            onChange={(event) => setTitleFa(event.target.value)}
            placeholder="کانال اطلاع‌رسانی"
          />
        </Field>

        <Field
          label={isPrivate ? 'لینک دعوت (اجباری)' : 'لینک دعوت (اختیاری)'}
          hint={
            isPrivate
              ? 'کانال خصوصی لینک ندارد که ساخته شود، پس بدون این کاربر راهی برای عضو شدن ندارد.'
              : 'برای کانال عمومی از روی شناسه ساخته می‌شود.'
          }
        >
          <Input
            dir="ltr"
            value={inviteUrl}
            onChange={(event) => setInviteUrl(event.target.value)}
            placeholder="https://t.me/+AbCdEf..."
          />
        </Field>

        <Button
          disabled={!canAdd}
          onClick={() =>
            void run(async () => {
              await routes.add({
                chatRef: ref,
                titleFa: titleFa.trim(),
                inviteUrl: inviteUrl.trim() || null,
              })
              setChatRef('')
              setTitleFa('')
              setInviteUrl('')
            })
          }
        >
          {'افزودن'}
        </Button>
      </div>
    </Card>
  )
}

const CONFIRM_REMOVE = 'این کانال از عضویت اجباری حذف شود؟'

const PLATFORM = {
  list: () => api.channels(),
  add: api.addChannel,
  setActive: api.setChannelActive,
  remove: api.removeChannel,
}

const MINE = {
  list: () => api.myChannels(),
  add: api.addMyChannel,
  setActive: api.setMyChannelActive,
  remove: api.removeMyChannel,
}
