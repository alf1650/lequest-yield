# LEQUEST · Yield Calculator

A single-file static dashboard for analysing the rental yield and total return of LEQUEST (2-bed, 2-bath, kids-pool access — second residential property).

Open `index.html` in a browser. All state is saved to `localStorage`; no backend.

## What it computes

| Metric | Formula |
|---|---|
| **Gross Yield** | Annual rent ÷ purchase price |
| **Net Yield** | (Annual rent − recurring expenses) ÷ total acquisition cost |
| **Cash-on-Cash** | (Rent − expenses − mortgage) ÷ cash actually invested |
| **IRR** | Bisection solver over yearly cashflows incl. terminal sale proceeds |
| **Break-even rent** | Monthly rent at which net cashflow = 0 |

## Defaults

- Purchase price: **S$900,000**
- BSD: **S$27,000** (3% flat — user-specified)
- ABSD: **S$63,000** (7%, second property)
- Legal: S$3,000
- Loan: 0 (cash purchase — fill in if mortgaged)
- Property tax: computed from Annual Value using SG **non-owner-occupied** progressive rates (12% / 20% / 28% / 36%)

## Notes

- BSD shown as a flat 3% per the user's recollection; actual SG BSD is tiered (1% / 2% / 3% / 4%) — override the field if you want exact figures.
- Income tax on rental is optional (toggle by setting tax rate > 0).
- IRR assumes annual cashflows and a single terminal sale.
- All numbers in SGD.
