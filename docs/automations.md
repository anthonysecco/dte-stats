# Automation examples

Replace the `switch.*` and `climate.*` entities with your own. Paste each into **Settings → Automations → ⋮ → Edit in YAML**.

## Keep a heater off during peak hours

Turns a hot tub or water heater element off when peak starts and back on when it ends. Most hot tubs keep their temperature for a few hours without heating; check yours first.

```yaml
alias: "Hot tub: no heating during peak"
triggers:
  - trigger: state
    entity_id: binary_sensor.dte_energy_peak_hours
actions:
  - action: "switch.turn_{{ 'off' if trigger.to_state.state == 'on' else 'on' }}"
    target:
      entity_id: switch.hot_tub_heater
mode: restart
```

## Charge the car overnight on D1.13

Start charging in the super off-peak window (1–7 am) and stop when it ends.

```yaml
alias: "EV: charge in super off-peak"
triggers:
  - trigger: state
    entity_id: sensor.dte_energy_price_period
actions:
  - action: "switch.turn_{{ 'on' if trigger.to_state.state == 'super_off_peak' else 'off' }}"
    target:
      entity_id: switch.ev_charger
mode: restart
```

## Pre-cool before the peak

Cool the house a little extra in the hour before peak starts, then let it drift.

```yaml
alias: "HVAC: pre-cool before peak"
triggers:
  - trigger: template
    value_template: >-
      {% set start = states('sensor.dte_energy_next_peak') %}
      {{ start not in ['unknown', 'unavailable'] and
         now() >= as_datetime(start) - timedelta(hours=1) and now() < as_datetime(start) }}
    id: precool
  - trigger: state
    entity_id: binary_sensor.dte_energy_peak_hours
    to: "on"
    id: coast
  - trigger: state
    entity_id: binary_sensor.dte_energy_peak_hours
    to: "off"
    id: normal
conditions:
  - condition: state
    entity_id: climate.living_room
    state: cool
actions:
  - action: climate.set_temperature
    target:
      entity_id: climate.living_room
    data:
      temperature: "{{ {'precool': 72, 'coast': 77, 'normal': 75}[trigger.id] }}"
mode: queued
```

## Tell me when a cheaper plan wins

```yaml
alias: "DTE: cheaper plan available"
triggers:
  - trigger: state
    entity_id: sensor.dte_energy_cheapest_plan
conditions:
  - condition: template
    value_template: >-
      {{ trigger.to_state.state not in ['unknown', 'unavailable'] and
         trigger.to_state.attributes.get('cost_' ~ trigger.to_state.state) is not none }}
actions:
  - action: persistent_notification.create
    data:
      title: DTE plan check
      message: >-
        Over the last 30 days, {{ states('sensor.dte_energy_cheapest_plan') }} would have been cheapest
        ({{ state_attr('sensor.dte_energy_cheapest_plan', 'cost_' ~ states('sensor.dte_energy_cheapest_plan')) }} USD
        in per-kWh charges).
mode: single
```
