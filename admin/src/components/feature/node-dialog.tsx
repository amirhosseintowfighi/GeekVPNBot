'use client'

import * as React from 'react'

import { ApiError, api } from '@/lib/api'
import type { NodeCreateBody, PanelRow } from '@/lib/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'
import type { PanelGroupOption } from '@/lib/types'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

/**
 * Creating a node.
 *
 * One dialog, two screens: "panels" and "servers" are the same resource seen
 * from two angles, which is why `api.servers()` and `api.panels()` are the
 * same GET. Both had a "new" button that did nothing at all - no handler, no
 * dialog, nothing behind it - so a fresh install had no way to add the one
 * thing without which nothing can be sold: provisioning picks a node from the
 * database, and an empty list fails every paid order.
 *
 * The panel kinds are the registry in `domain/panels/enums.py`. Adding one
 * there means adding it here; there is no way to discover them at runtime and
 * inventing an endpoint for five constants would be worse.
 */
const PANEL_KINDS = [
  { value: 'pasarguard', label: 'PasarGuard' },
  { value: 'marzban', label: 'Marzban' },
  { value: 'marzneshin', label: 'Marzneshin' },
  { value: 'sanaei', label: '3x-ui (Sanaei)' },
  { value: 'alireza', label: 'x-ui (Alireza)' },
] as const

const ID_PATTERN = /^[a-z0-9][a-z0-9_-]*$/

export function NodeDialog({
  open,
  node,
  onClose,
  onCreated,
}: {
  open: boolean
  /** The node being edited, or null to create one. */
  node?: PanelRow | null
  onClose: () => void
  onCreated: () => void
}) {
  const [id, setId] = React.useState('')
  const [nameFa, setNameFa] = React.useState('')
  const [panelKind, setPanelKind] = React.useState<string>('marzban')
  const [baseUrl, setBaseUrl] = React.useState('')
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [countryCode, setCountryCode] = React.useState('')
  const [capacity, setCapacity] = React.useState('')
  const [verifyTls, setVerifyTls] = React.useState(true)
  // PasarGuard grants access through groups, and which group an account
  // joins decides which configs it receives. Read from the panel rather than
  // typed, because a wrong id produces a working account carrying nothing the
  // customer can use - a failure that looks like a broken server for a week.
  const [groups, setGroups] = React.useState<PanelGroupOption[]>([])
  const [chosenGroups, setChosenGroups] = React.useState<string[]>([])
  const [groupsNote, setGroupsNote] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [failure, setFailure] = React.useState<string | null>(null)

  const editing = Boolean(node)

  // Load the node being edited, and clear the form when it changes. The
  // password is never sent back by the API - only `hasPassword` - so it starts
  // blank and an untouched field leaves the stored one alone.
  React.useEffect(() => {
    setId(node?.id ?? '')
    setNameFa(node?.nameFa ?? '')
    setPanelKind(node?.panelKind ?? 'marzban')
    setBaseUrl(node?.baseUrl ?? '')
    setUsername(node?.username ?? '')
    setPassword('')
    setCountryCode(node?.countryCode ?? '')
    setCapacity(String(node?.capacity ?? ''))
    setVerifyTls(node?.verifyTls ?? true)
    setFailure(null)
    setGroups([])
    setGroupsNote(null)
    setChosenGroups(
      Array.isArray(node?.config?.defaultGroups)
        ? (node.config.defaultGroups as string[]).map(String)
        : [],
    )
  }, [node, open])

  // Only for a node that exists: listing groups means logging in to the panel,
  // and there are no stored credentials until it has been saved once.
  React.useEffect(() => {
    if (!open || !node) return
    let cancelled = false
    void api
      .panelGroups(node.id)
      .then((result) => {
        if (cancelled) return
        if (!result.supported) {
          setGroupsNote('این پنل مفهوم گروه ندارد.')
          return
        }
        if (!result.ok) {
          setGroupsNote(result.message ?? 'خواندن گروه‌ها از پنل ممکن نشد.')
          return
        }
        setGroups(result.groups)
        setGroupsNote(result.groups.length === 0 ? 'این پنل هنوز گروهی ندارد.' : null)
      })
      .catch(() => {
        if (!cancelled) setGroupsNote('خواندن گروه‌ها از پنل ممکن نشد.')
      })
    return () => {
      cancelled = true
    }
  }, [node, open])

  const idValid = ID_PATTERN.test(id)
  const complete = editing
    ? nameFa.trim() !== '' && baseUrl.trim() !== '' && username !== ''
    : idValid && nameFa.trim() !== '' && baseUrl.trim() !== '' && username !== '' && password !== ''

  const reset = () => {
    setId('')
    setNameFa('')
    setBaseUrl('')
    setUsername('')
    setPassword('')
    setCountryCode('')
    setCapacity('')
    setVerifyTls(true)
    setFailure(null)
  }

  const submit = async () => {
    setBusy(true)
    setFailure(null)
    try {
      const shared = {
        nameFa: nameFa.trim(),
        baseUrl: baseUrl.trim(),
        username: username.trim(),
        // Two characters or nothing: the API rejects a one-letter code, and an
        // empty string is not the same as "not set".
        countryCode: countryCode.trim().length === 2 ? countryCode.trim().toUpperCase() : null,
        // Zero means "no declared ceiling", which is what NodeRecord.has_room
        // reads it as.
        capacity: Number(capacity.replace(/\D/g, '')) || 0,
        verifyTls,
      }

      if (node) {
        // PATCH, and only what changed. A blank password means "leave it
        // alone" - sending an empty one would wipe the stored credential and
        // the next provision would fail authentication.
        await api.updatePanel(node.id, {
          ...shared,
          ...(password ? { password } : {}),
          // Sent whenever groups were readable, including when the operator
          // cleared them: an empty list is a decision, and merging would give
          // no way to make it.
          ...(groups.length > 0 ? { config: { defaultGroups: chosenGroups } } : {}),
        })
      } else {
        const body: NodeCreateBody = {
          ...shared,
          id: id.trim(),
          panelKind,
          password,
        }
        await api.savePanel(body)
      }
      onCreated()
      onClose()
      reset()
    } catch (thrown) {
      setFailure(thrown instanceof ApiError ? thrown.messageFa : '')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? 'ویرایش سرور' : 'سرور جدید'}</DialogTitle>
          <DialogDescription>
            {'اعتبارنامه‌ی پنل رمزنگاری‌شده ذخیره می‌شود. بعد از ساخت، اتصال را تست کنید.'}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3">
          <Field
            label={'شناسه'}
            hint={'حروف کوچک انگلیسی، عدد، خط تیره. بعداً قابل تغییر نیست.'}
            error={id !== '' && !idValid ? 'فقط حروف کوچک، عدد، _ و -' : null}
          >
            <Input
              ltr
              disabled={editing}
              value={id}
              onChange={(event) => setId(event.target.value.toLowerCase())}
              placeholder="de-frankfurt-1"
              autoFocus={!editing}
            />
          </Field>

          <Field label={'نام نمایشی'} hint={'همین نام را مشتری می‌بیند'}>
            <Input
              value={nameFa}
              onChange={(event) => setNameFa(event.target.value)}
              placeholder={'آلمان - فرانکفورت'}
            />
          </Field>

          <Field label={'نوع پنل'}>
            <Select value={panelKind} onValueChange={setPanelKind} disabled={editing}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PANEL_KINDS.map((kind) => (
                  <SelectItem key={kind.value} value={kind.value}>
                    {kind.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            label={'آدرس پنل'}
            hint={'فقط ریشه، بدون مسیر. «/dashboard» صفحه‌ای است که خودتان می‌بینید، نه ریشه‌ی API.'}
          >
            <Input
              ltr
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://panel.example.com"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label={'نام کاربری پنل'}>
              <Input
                ltr
                autoComplete="off"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </Field>

            <Field
              label={'گذرواژه پنل'}
              hint={editing ? 'خالی بگذارید تا تغییر نکند' : undefined}
            >
              <Input
                ltr
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label={'کد کشور'} hint={'دو حرف، مثل DE. اختیاری.'}>
              <Input
                ltr
                maxLength={2}
                value={countryCode}
                onChange={(event) => setCountryCode(event.target.value)}
                placeholder="DE"
              />
            </Field>

            <Field label={'ظرفیت'} hint={'صفر یعنی بدون سقف'}>
              <Input
                ltr
                inputMode="numeric"
                value={capacity}
                onChange={(event) => setCapacity(event.target.value)}
                placeholder="0"
              />
            </Field>
          </div>

          <label className="flex items-center justify-between rounded-md border border-border px-3 py-2">
            <span className="text-xs">
              {'بررسی گواهی TLS'}
              <span className="block text-2xs text-muted-foreground">
                {'فقط برای پنلی با گواهی self-signed خاموش کنید'}
              </span>
            </span>
            <Switch checked={verifyTls} onCheckedChange={setVerifyTls} />
          </label>

          {/*
            Groups, for panels that have them.

            Only shown for a saved node: listing them means logging in, and
            there are no stored credentials until the node exists. A new node
            is therefore created first and its groups chosen on the next open,
            which is also the order that lets the operator confirm the panel is
            reachable before making a selling decision on top of it.
          */}
          {node ? (
            <div className="space-y-2">
              <p className="text-2xs font-medium">{'گروه‌های دسترسی'}</p>
              {groupsNote ? (
                <p className="text-2xs text-muted-foreground">{groupsNote}</p>
              ) : null}
              {groups.length > 0 ? (
                <>
                  <div className="flex flex-wrap gap-1.5">
                    {groups.map((group) => {
                      const picked = chosenGroups.includes(group.id)
                      return (
                        <button
                          key={group.id}
                          type="button"
                          onClick={() =>
                            setChosenGroups((current) =>
                              picked
                                ? current.filter((value) => value !== group.id)
                                : [...current, group.id],
                            )
                          }
                          className={
                            'rounded-md border px-2 py-1 text-2xs transition-colors ' +
                            (picked
                              ? 'border-primary bg-primary/10 text-primary'
                              : 'border-border text-muted-foreground hover:text-foreground')
                          }
                        >
                          {group.name}
                          {group.isDefault ? ' ★' : ''}
                        </button>
                      )
                    })}
                  </div>
                  <p className="text-2xs text-muted-foreground">
                    {'اکانت‌های ساخته‌شده روی این سرور به گروه‌های انتخاب‌شده اضافه می‌شوند. اگر هیچ‌کدام انتخاب نشود، پیش‌فرض خود پنل اعمال می‌شود.'}
                  </p>
                </>
              ) : null}
            </div>
          ) : null}

          {failure ? (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
              {failure}
            </p>
          ) : null}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {'انصراف'}
          </Button>
          <Button loading={busy} disabled={!complete} onClick={submit}>
            {editing ? 'ذخیره' : 'ساخت سرور'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
