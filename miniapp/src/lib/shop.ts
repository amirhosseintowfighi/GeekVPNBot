/**
 * Which shop the Mini App is open in.
 *
 * A reseller's bot opens the app with `?shop=<their id>`. Telegram keeps the
 * query on the first load only - the app's own navigation drops it - so it is
 * kept in sessionStorage for the life of the webview. Every API call sends it
 * back (`X-Shop`), and the server checks the initData against that shop's own
 * bot before believing it.
 *
 * The same lookup runs, as plain JS, in the script `layout.tsx` puts in the
 * head, so the classic theme is on <html> before the first paint rather than
 * flashing our blue at a reseller's customer.
 */

export const SHOP_KEY = 'geek.shop'
const SHOP_ID = /^[0-9a-f]{32}$/

export function resolveShop(search: string, stored: string | null): string | null {
  const fromUrl = new URLSearchParams(search).get('shop')
  if (fromUrl && SHOP_ID.test(fromUrl)) return fromUrl
  return stored && SHOP_ID.test(stored) ? stored : null
}

/** The shop id, or null in our own app. */
export function shopId(): string | null {
  if (typeof window === 'undefined') return null
  let stored: string | null = null
  try {
    stored = window.sessionStorage.getItem(SHOP_KEY)
  } catch {
    // Storage blocked: the URL is still read.
  }
  const shop = resolveShop(window.location.search, stored)
  if (shop && shop !== stored) {
    try {
      window.sessionStorage.setItem(SHOP_KEY, shop)
    } catch {
      // Best effort; this load still knows its shop.
    }
  }
  return shop
}

/** The head script: same rule as `resolveShop`, applied before React loads. */
export const THEME_BOOTSTRAP = `(function(){try{var r=/^[0-9a-f]{32}$/,q=new URLSearchParams(location.search).get('shop'),k='${SHOP_KEY}',s=null;try{s=sessionStorage.getItem(k)}catch(e){}var v=q&&r.test(q)?q:(s&&r.test(s)?s:null);if(v){try{sessionStorage.setItem(k,v)}catch(e){}document.documentElement.setAttribute('data-theme','classic')}}catch(e){}})()`
