# \u062f\u0633\u062a\u0631\u0633\u06cc\u200c\u0647\u0627

38 permissions, 5 roles. `owner` is not in the matrix at all \u2014 it is granted
everything by short-circuit, so adding a new permission can never accidentally
lock the owner out.

## The invariants worth knowing

1. **An edit permission never exists without its view permission.** A screen
   you cannot open is a permission you cannot exercise. Enforced by test.
2. **`viewer` holds only `.view` permissions.** Enforced by test.
3. **`finance` can read tickets but not reply.** Money people reconcile
   refunds against conversations; support owns the voice of the brand.
4. **`support` can reject a bogus receipt but never refund.** Rejecting
   declines money that was never taken; refunding returns money that was.
5. **`permissions.edit` and `users.impersonate` belong to the owner alone.**
6. **`canAssignRole(actor, target)`** is false when
   `ROLE_RANK[target] >= ROLE_RANK[actor]`, and always false when the target
   is `owner`. `finance` and `support` share rank 2, so neither can reassign
   the other. There is no chain of legal assignments that reaches `admin`
   from below \u2014 that is the whole point.

Ownership transfer is deliberately not a dropdown. A compromised owner
session would otherwise be a permanent takeover.
