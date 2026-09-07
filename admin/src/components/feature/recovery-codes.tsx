'use client'

import * as React from 'react'

import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'

/**
 * Issue a fresh set of single-use recovery codes.
 *
 * The codes are readable exactly once - only their hashes are stored - so the
 * copy has to say that plainly, before the button rather than after it. An
 * operator who closes this card without writing them down has nothing, and
 * finding that out on the day their phone is gone is the whole failure this
 * feature exists to prevent.
 */
export function RecoveryCodes() {
  const [codes, setCodes] = React.useState<string[] | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [failure, setFailure] = React.useState<string | null>(null)

  const issue = async () => {
    if (
      !window.confirm(
        'یه مجموعهٔ تازه ساخته می‌شه و کدهای قبلیت از کار می‌افتن. ادامه می‌دی؟',
      )
    ) {
      return
    }
    setBusy(true)
    setFailure(null)
    try {
      const result = await api.issueRecoveryCodes()
      setCodes(result.codes)
    } catch {
      setFailure('ساخت کدها انجام نشد. دوباره امتحان کن.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="text-sm font-medium">کدهای بازیابی</div>
      <p className="text-sm leading-loose text-muted-foreground">
        اگه گوشیِ اپلیکیشن دومرحله‌ای رو از دست بدی، با یکی از این کدها وارد پنل
        می‌شی. هر کد فقط یک بار کار می‌کنه.
      </p>
      <p className="text-sm leading-loose text-muted-foreground">
        فقط همین یک بار نشونت داده می‌شن — ما فقط هَششون رو نگه می‌داریم. یه جای
        امن بنویس یا چاپشون کن، همین حالا.
      </p>

      {codes ? (
        <div className="space-y-2">
          <div
            dir="ltr"
            className="grid grid-cols-2 gap-2 rounded-md border bg-secondary/30 p-3 font-mono text-sm"
          >
            {codes.map((code) => (
              <span key={code}>{code}</span>
            ))}
          </div>
          <Button
            variant="secondary"
            onClick={() => navigator.clipboard?.writeText(codes.join('\n'))}
          >
            کپی همه
          </Button>
        </div>
      ) : null}

      {failure ? <p className="text-xs text-destructive">{failure}</p> : null}

      <Button onClick={issue} loading={busy} disabled={busy}>
        {codes ? 'ساخت مجموعهٔ تازه' : 'ساخت کدهای بازیابی'}
      </Button>
    </div>
  )
}
