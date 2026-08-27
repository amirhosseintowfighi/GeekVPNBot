'use client'

import * as React from 'react'
import { useSearchParams } from 'next/navigation'

import { api, ApiError } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/input'

const MIN_LENGTH = 12

/**
 * Choosing a first password.
 *
 * Where an approved reseller lands from the link their operator forwarded. The
 * link carries a one-time token; this page trades it for a password only they
 * have seen, so a live credential never travels through a chat.
 *
 * No session is issued on success. They sign in the ordinary way afterwards,
 * which is one fewer path in this system that mints a credential - and it also
 * proves the password works before they close the tab.
 *
 * The token is read from the URL and never stored. It is spent on submit and
 * dead immediately after, so a tab left open or a URL in someone's history is
 * a string that does nothing.
 */
export default function SetPasswordPage() {
  return (
    <React.Suspense fallback={null}>
      <SetPasswordForm />
    </React.Suspense>
  )
}

function SetPasswordForm() {
  const params = useSearchParams()
  const adminId = params.get('a') ?? ''
  const token = params.get('t') ?? ''

  const [password, setPassword] = React.useState('')
  const [again, setAgain] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [done, setDone] = React.useState(false)
  const [submitting, setSubmitting] = React.useState(false)

  const tooShort = password.length > 0 && password.length < MIN_LENGTH
  const mismatch = again.length > 0 && again !== password
  const ready = password.length >= MIN_LENGTH && again === password && !!adminId && !!token

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.setPassword({ adminId, token, password })
      setDone(true)
    } catch (thrown) {
      setError(
        thrown instanceof ApiError
          ? thrown.messageFa
          : 'تغییر رمز انجام نشد. لینک ممکن است منقضی شده باشد.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  if (!adminId || !token) {
    return (
      <Shell title="لینک نامعتبر است">
        <p className="text-sm text-muted-foreground">
          این لینک کامل نیست. از کسی که آن را برایتان فرستاده بخواهید دوباره
          ارسال کند.
        </p>
      </Shell>
    )
  }

  if (done) {
    return (
      <Shell title="رمز شما ساخته شد">
        <p className="text-sm text-muted-foreground">
          حالا می‌توانید با نام کاربری و همین رمز وارد پنل شوید. این لینک دیگر
          کار نمی‌کند.
        </p>
        <Button className="mt-4 w-full" onClick={() => (window.location.href = '/sign-in')}>
          ورود به پنل
        </Button>
      </Shell>
    )
  }

  return (
    <Shell
      title="ساخت رمز عبور"
      description="یک رمز برای خودتان انتخاب کنید. این لینک فقط یک بار کار می‌کند."
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label="رمز عبور" hint={`حداقل ${MIN_LENGTH} کاراکتر`}>
          <Input
            dir="ltr"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>
        {tooShort ? (
          <p className="text-sm text-destructive">رمز باید حداقل {MIN_LENGTH} کاراکتر باشد.</p>
        ) : null}
        <Field label="تکرار رمز عبور">
          <Input
            dir="ltr"
            type="password"
            autoComplete="new-password"
            value={again}
            onChange={(event) => setAgain(event.target.value)}
          />
        </Field>
        {mismatch ? <p className="text-sm text-destructive">دو رمز یکی نیستند.</p> : null}
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        <Button type="submit" className="w-full" disabled={!ready || submitting}>
          {submitting ? 'در حال ثبت…' : 'ثبت رمز'}
        </Button>
      </form>
    </Shell>
  )
}

function Shell({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </CardHeader>
        <CardContent>{children}</CardContent>
      </Card>
    </div>
  )
}
