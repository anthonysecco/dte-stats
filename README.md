# DTE Energy for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub release](https://img.shields.io/github/v/release/anthonysecco/dte-stats)](https://github.com/anthonysecco/dte-stats/releases)
[![Validate](https://github.com/anthonysecco/dte-stats/actions/workflows/validate.yml/badge.svg)](https://github.com/anthonysecco/dte-stats/actions/workflows/validate.yml)
[![Tests](https://github.com/anthonysecco/dte-stats/actions/workflows/tests.yml/badge.svg)](https://github.com/anthonysecco/dte-stats/actions/workflows/tests.yml)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-donate-yellow.svg)](https://www.buymeacoffee.com/anthonysecco)

Home Assistant integration for **DTE Energy** customers in Michigan. It reads your usage from DTE's Green Button data link and gives you:

- **Energy dashboard history**: hourly electricity and daily gas use, with costs, going back about 13 months.
- **Cost sensors**: last day and month to date, for electricity and gas.
- **Plan comparison**: what the last 30 days would have cost on each DTE time-of-day plan, and which is cheapest.
- **Live price and peak sensors** for your plan, for automations such as running the dishwasher, EV charger or hot tub heater outside peak hours.

No DTE login is stored: only the shareable link.

> **Unofficial.** This project is not affiliated with or endorsed by DTE Energy. It reads the Green Button usage file DTE makes available to its customers and prices it with DTE's published rate books. Either can change without notice.

## Contents
- [What you need](#what-you-need)
- [Get your usage data link](#get-your-usage-data-link)
- [Installation](#installation)
- [Configuration](#configuration)
- [Add it to the Energy dashboard](#add-it-to-the-energy-dashboard)
- [Entities](#entities)
- [Plans and prices](#plans-and-prices)
- [Automations](#automations)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Support](#-support)

## What you need

- DTE residential electric service with a smart meter (gas is optional).
- Home Assistant 2026.3 or newer, with the recorder enabled (it is by default).
- A usage data link from your DTE account (below).

## Get your usage data link

1. Sign in at dteenergy.com and open **Usage → Usage History** (the exact labels may vary).
2. Choose the option to share or export your **Green Button** data, and create a link.
3. Copy the link. It looks like `https://usagedata.dteenergy.com/link/` followed by a long code.

**Treat the link like a password**: anyone who has it can see your usage. The integration stores it as a secret and leaves it out of diagnostics. Never paste it into an issue.

DTE doesn't say how long a link stays valid. If it stops working, Home Assistant shows a repair notice; create a new link and use **Reconfigure** (below). Your history is kept.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=anthonysecco&repository=dte-stats&category=integration)

Or add it by hand:
1. In Home Assistant open **HACS**, then the **⋮** menu (top right), then **Custom repositories**.
2. Repository: `https://github.com/anthonysecco/dte-stats`. Type: **Integration**. Click **Add**.
3. Search HACS for **DTE Energy**, open it and click **Download**.
4. **Restart Home Assistant.**
5. Add the integration (next section).

Requires Home Assistant **2026.3** or newer.

### Manual
Copy `custom_components/dte_stats` from the [latest release](https://github.com/anthonysecco/dte-stats/releases) into your `config/custom_components/` folder, then restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up DTE Energy.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dte_stats)

**Settings → Devices & services → Add integration → DTE Energy.** Paste your usage data link and pick the electric plan on your bill. Setup downloads the file once to check it, then creates a **DTE Energy** device.

The first download imports all the history in the file (about 13 months); it can take a minute.

### Options

**Settings → Devices & services → DTE Energy → Configure.** Saving reloads the integration.

- **Electric plan**: the plan used for costs and the price and peak sensors.
- **Check for new data every**: 1 to 24 hours (default 6). DTE updates once a day or so.
- **Reconfigure** (device page menu): paste a new link when the old one stops working.

## Add it to the Energy dashboard

Open **Settings → Dashboards → Energy**:

- **Electricity grid → Add consumption**: choose **DTE electric consumption**. For cost, choose **Use an entity tracking the total costs** and pick **DTE electric cost**.
- **Gas consumption → Add gas source**: choose **DTE gas consumption**, and for cost **DTE gas cost**.

These are imported statistics, so they show usage at the hour it happened even though DTE publishes it a day or two later. Expect the dashboard to be one to two days behind.

## Entities

| Entity | What it shows |
| --- | --- |
| Electricity last day / this month | kWh for the newest complete day in DTE's data, and that month to date |
| Electricity cost last day / this month | USD at your plan's prices (per-kWh charges; the `monthly_fixed_charges` attribute has the $10 fixed charges) |
| Gas last day / this month, Gas cost … | CCF and USD (gas supply, reservation and distribution charges; plus a $15.40 monthly customer charge, shown as an attribute) |
| Peak share | % of your electricity used in your plan's peak hours, last 30 days |
| Cheapest plan | Which plan would have cost least over the last 30 days; attributes give each plan's cost |
| Electricity price | USD/kWh right now on your plan, including delivery and surcharges. Also has the solar export credit as an attribute |
| Price period | Peak, off-peak or super off-peak (D1.13) right now |
| Next peak | When the next peak period starts |
| Peak hours (binary sensor) | On during peak hours |
| Data through (diagnostic) | How recent DTE's data is, plus how many readings DTE marked as estimated |

Gas entities appear only when your link includes gas; electric and price entities only when it includes electricity.

## Plans and prices

| Plan | Peak hours (weekdays) | Notes |
| --- | --- | --- |
| D1.11 Standard time of day | 3–7 pm | DTE's default residential plan; summer is June–September |
| D1.2 Time of day 11 am–7 pm | 11 am–7 pm | Cheaper off-peak, pricier peak; summer is June–October |
| D1.13 Overnight savers | 3–7 pm | Cheapest 1–7 am every day; limited enrollment |

Prices come from DTE's rate books (electric base rates effective March 5, 2026; fuel charge and surcharges current as of October 2026; gas cost factors by month). A kWh's price is power supply + distribution + per-kWh surcharges. Costs leave out fixed monthly charges, credits and sales tax, so they will be a little under your bill.

Changing the plan in **Configure** affects new costs and the live sensors; costs already imported keep the plan they were priced with. Prices are updated in new releases when DTE changes them.

## Automations

See [docs/automations.md](docs/automations.md), for example keeping a hot tub or water heater off during peak hours.

## Limitations

- **Delay**: DTE publishes usage a day or two late. This integration is for history, costs and plan choice, not real-time monitoring.
- **Gas readings are daily**, and DTE fills in many days by estimating between meter reads; the Data through sensor counts them.
- **Prices change** with each DTE rate case and month; check the `rates_as_of` attribute on the price sensor.
- Only the D1.11, D1.2 and D1.13 electric plans and gas Rate A are priced.

## Troubleshooting

- **"DTE didn't return usage data for this link"**: the link expired or was copied incompletely. Create a new one.
- **Energy dashboard shows nothing for today**: expected; DTE's data runs a day or two behind.
- **Costs differ from the bill**: the bill adds fixed charges, taxes and any credits, and the billing period differs from calendar months.

- **Diagnostics:** **Settings → Devices & services → DTE Energy → ⋮ → Download diagnostics** shows what the file covers, without the link or your readings. Attach it to [issues](https://github.com/anthonysecco/dte-stats/issues).
- **Debug logging:**
  ```yaml
  logger:
    logs:
      custom_components.dte_stats: debug
  ```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
ruff check .
pytest
```

CI runs HACS validation, hassfest, ruff and pytest on every push. Tests use a generated usage file in DTE's format with made-up numbers; no real account data or link is used.

## 💖 Support

If you found this project useful, consider buying me a coffee. ☕

<a href="https://www.buymeacoffee.com/anthonysecco"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" height="60" width="217"></a>

## AI Disclosure

This project was built largely with AI coding tools (Claude). I directed the design and reviewed the changes, but most of the code and documentation was written by AI. Please review the code before relying on it, and open an issue if you find a problem.

## License

MIT
