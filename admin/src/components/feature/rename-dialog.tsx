'use client'

import * as React from 'react'

import { ApiError } from '@/lib/api'
import { normalizeInput } from '@/lib/fa'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'

/**
 * Renaming anything in the catalogue.
 *
 * `PATCH` has existed on categories, products and plans since the catalogue was
 * written, and no screen ever called any of it - so a name typed once could
 * never be corrected, and the only way to fix a typo was to create a second row
 * and archive the first.
 *
 * One dialog for all three rather than three nearly identical ones: the field
 * is the same field, and the differences are the title and which save function
 * gets called.
 */
export function RenameDialog({
  open,
  title,
  currentName,
  onClose,
  onSave,
}: {
  open: boolean
  title: string
  currentName: string
  onClose: () => void
  onSave: (nameFa: string) => Promise<unknown>
}) {
  const [name, setName] = React.useState(currentName)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  // The row behind the dialog changes as the operator opens a different one,
  // and a stale field would rename the wrong thing with the wrong text.
  React.useEffect(() => {
    if (open) {
      setName(currentName)
      setError(null)
    }
  }, [open, currentName])

  const cleaned = normalizeInput(name).trim()

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await onSave(cleaned)
      onClose()
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'ذخیره نشد.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <Field label="نام">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && cleaned.length > 0 && !busy) void save()
            }}
            autoFocus
          />
        </Field>

        {error ? <p className="text-2xs text-destructive">{error}</p> : null}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {'انصراف'}
          </Button>
          <Button
            loading={busy}
            disabled={cleaned.length === 0 || cleaned === currentName}
            onClick={() => void save()}
          >
            {'ذخیره'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
