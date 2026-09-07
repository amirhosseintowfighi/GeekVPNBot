'use client'

import * as React from 'react'

import { api, ApiError } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/input'

/**
 * The sign-in screen.
 *
 * Every 401 in the panel redirects here - `guard.tsx` on a failed session read,
 * `topbar.tsx` after signing out - and the route did not exist, so an operator
 * who was not already signed in landed on a 404 with no way forward. The panel
 * had no way in at all.
 *
 * There is no token handling here on purpose. The backend answers this login
 * with an httpOnly cookie, so the browser carries the session and JavaScript
 * never holds a credential. A full page load, not a router push, is what makes
 * the session provider re-read `/auth/me` with that cookie in place.
 */
export default function SignInPage() {
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [totpCode, setTotpCode] = React.useState('')
  const [recoveryCode, setRecoveryCode] = React.useState('')
  const [useRecovery, setUseRecovery] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [submitting, setSubmitting] = React.useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.signIn({
        username: username.trim(),
        password,
        // An operator without 2FA must not send an empty string: the backend
        // reads a present code as a claim to have one and rejects it.
        totpCode: useRecovery ? undefined : totpCode.trim() || undefined,
        recoveryCode: useRecovery ? recoveryCode.trim() || undefined : undefined,
      })
      window.location.href = '/'
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.messageFa
          : 'ورود ناموفق بود.',
      )
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>{'ورود به پنل'}</CardTitle>
          <CardDescription>
            {'برای ادامه، وارد حساب مدیریتیت شو.'}
          </CardDescription>
        </CardHeader>

        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <Field label={'نام کاربری'} htmlFor="username" required>
              <Input
                id="username"
                name="username"
                autoComplete="username"
                autoFocus
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </Field>

            <Field label={'گذرواژه'} htmlFor="password" required>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </Field>

            {useRecovery ? (
              <Field
                label={'کد بازیابی'}
                htmlFor="recovery"
                hint={'یکی از کدهایی که موقع فعال کردن دومرحله‌ای گرفتی. هر کد فقط یک بار کار می‌کنه.'}
              >
                <Input
                  id="recovery"
                  name="recovery"
                  dir="ltr"
                  autoComplete="off"
                  placeholder="XXXX-XXXX"
                  value={recoveryCode}
                  onChange={(event) => setRecoveryCode(event.target.value)}
                />
              </Field>
            ) : (
              <Field
                label={'کد دومرحله‌ای'}
                htmlFor="totp"
                hint={'اگه فعال نیست، خالی بذار.'}
              >
                <Input
                  id="totp"
                  name="totp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  dir="ltr"
                  value={totpCode}
                  onChange={(event) => setTotpCode(event.target.value)}
                />
              </Field>
            )}

            <button
              type="button"
              className="text-start text-xs text-muted-foreground underline"
              onClick={() => setUseRecovery((current) => !current)}
            >
              {useRecovery
                ? 'برگرد به کد دومرحله‌ای'
                : 'گوشیت رو نداری؟ با کد بازیابی وارد شو'}
            </button>

            {error ? (
              <p role="alert" className="text-xs text-destructive">
                {error}
              </p>
            ) : null}

            <Button type="submit" full loading={submitting} disabled={submitting}>
              {'ورود'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
