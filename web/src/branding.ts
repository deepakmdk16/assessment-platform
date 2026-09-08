/** The product name, in one place.
 *
 *  It was hardcoded in seven files — the sidebar, five auth screens and the
 *  candidate footer — which made white-labelling (listed under X10 as a
 *  first-paying-customer gap) a find-and-replace rather than a setting.
 *
 *  `VITE_PRODUCT_NAME` lets a deployment rename it at build time. The candidate
 *  footer is the one that matters commercially: it is the only place the
 *  platform's own name appears in front of someone else's candidates.
 */
export const PRODUCT_NAME = import.meta.env.VITE_PRODUCT_NAME ?? 'assess.dev'
