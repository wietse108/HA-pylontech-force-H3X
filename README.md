# Pylontech Force H3X Integration for Home Assistant via Modbus TCP

![HACS Custom](https://img.shields.io/badge/HACS-Custom_Repository-orange.svg?style=for-the-badge)
![Version](https://img.shields.io/badge/version-0.1.0-blue.svg?style=for-the-badge)
![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg?style=for-the-badge)

A fully native, UI-configurable Home Assistant custom integration for the **Pylontech Force H3X** inverter and BMS system. 

Say goodbye to complex, manual Modbus YAML configurations! This integration connects directly to your inverter over Modbus TCP, utilizing smart chunk-reading to poll dozens of registers efficiently without overloading the inverter's WiFi dongle.

---

## ✨ Features

- **UI Config Flow:** Set up your inverter in seconds via the Home Assistant integrations page. No YAML required!
- **Smart Chunk Polling:** Reads all required data from both the Inverter (Slave 2) and the BMS (Slave 1) in highly optimized, delay-spaced blocks to prevent Modbus timeouts.
- **Interactive Controls:** Not just reading data! Set your EMS mode, charge/discharge power limits, and SOC limits directly from the Home Assistant UI.
- **Auto-Discovery:** Automatically creates and groups all sensors and controls under a single Device in your dashboard.
- **Energy Dashboard Ready:** All energy/power sensors are configured with the correct `state_class` and `device_class` to work out-of-the-box with the Home Assistant Energy Dashboard.
- **Resilient Connection:** Built-in auto-reconnect and error handling.

## 📊 Included Sensors & Controls

This integration pulls comprehensive data from both the Inverter and the internal Battery Management System (BMS), and allows you to control the system.

**🎛️ Controls & Settings:**
* **EMS Mode Selector:** Switch between modes like `Self-Consumption`, `Back up mode`, and `User mode`.
* **Charge/Discharge Power Ref:** Set the exact percentage (-100% to 100%) for battery charging or discharging.
* **SOC Limits:** Sliders for setting the `Charge Limit SOC` and `Discharge Limit SOC (EPS)`.
* **Period Schedules:** Turn your pre-programmed Charging Schedules ON/OFF

**📡 Read-Only Sensors:**
* **🌞 Solar (PV):** Voltage, Current, and Power for PV1, PV2, and PV3, plus Total PV Energy.
* **⚡ Grid & AC:** Grid Import/Export, AC Total Power, Load Power, Phase Voltages (R/S/T), AC Frequency, and Total Grid Energy.
* **🔋 Battery (Inverter perspective):** Charge/Discharge Power, Voltage, Current, SOC, and Total Charge/Discharge Energy.
* **🧠 BMS (Internal):** Cell Voltage Max/Min, BMS Temperature, BMS SOC, State of Health (SOH), and total battery cycles.
* **🛠️ Status:** Inverter Status, Battery Status, and internal temperatures.

---

## ⚠️ Important Note: Charge & Discharge Control

If you want to use the **Charge/Discharge Power Ref** setting to manually force the battery to charge or discharge, **you MUST set the `EMS Mode` to `User mode`**. 
If the system is set to any other mode (like `Self-Consumption`), the inverter's internal logic will override your command and revert the setting back to its default value!

After the writing new settings, not all of the entities show the right value. I'm still working on that

---
## 📅 EMS Charge/Discharge Schedules (with v1.1.4)

If you have configured Charge/Discharge period schedules (up to 4 of them) in the Pylontech app, you can now enable or disable those schedules directly from Home Assistant.

⚠️ This integration can currently only toggle schedules on/off — it cannot view or edit the schedule contents (times, days, power settings).

### 📱 Where to configure schedules

Schedules must be configured in the Pylontech app:

* Device → Setting → Energy Management → Charge/Discharge Time Control

Configure each period as needed (time of day, days of week, etc), click Save, then use Home Assistant to activate or deactivate them.

### ⚙️ How it works
Each schedule appears in Home Assistant as below, and can be turned ON or OFF as required
* switch.pylontech_force_h3x_period_1
* switch.pylontech_force_h3x_period_2
* switch.pylontech_force_h3x_period_3
* switch.pylontech_force_h3x_period_4

### ⚠️ Important Note - No overlap allowed
Active schedules timings must not overlap. Overlapping periods may fail to activate or behave unpredictably.
Recommended approach
Use clean boundaries between periods. For example:
* Period 1: 07:00 → 10:59
* Period 2: 11:00 → 16:59

App remains the source of truth, and all schedule details must be configured in the app first.

---

## 🚀 Installation

### Option 1: Via HACS (Recommended)
This integration is easily installable via the [Home Assistant Community Store (HACS)](https://hacs.xyz/).

1. Open Home Assistant and navigate to **HACS** > **Integrations**.
2. Click the three dots (`...`) in the top right corner and select **Custom repositories**.
3. Paste the URL of this GitHub repository.
4. Select **Integration** as the category and click **Add**.
5. Close the popup, search for **Pylontech Force H3X** in HACS, and click **Download**.
6. **Restart Home Assistant.**

### Option 2: Manual Installation
1. Download the latest release from this repository.
2. Copy the `custom_components/pylon_fh3x` folder into your Home Assistant `custom_components` directory.
3. **Restart Home Assistant.**

---

## ⚙️ Configuration

1. In Home Assistant, go to **Settings** > **Devices & Services**.
2. Click the **+ Add Integration** button in the bottom right.
3. Search for **Pylontech Force H3X**.
4. Enter the **IP Address** of your inverter and the **Port** (default is `502`).
5. Click **Submit**. Your sensors will appear immediately!

> **⚠️ Important Notice regarding Modbus TCP:** > Modbus TCP usually allows only **one active connection at a time**. If you have an old YAML Modbus configuration in your `configuration.yaml` or another script reading from the inverter, you MUST disable/remove it and restart Home Assistant before adding this integration. Otherwise, the connection will be refused.

---

## 🔮 Roadmap
- [x] Read Inverter Holding Registers (Power, Voltage, Energy)
- [x] Read BMS Registers (Cell voltages, Temperatures, SOH)
- [x] Add `number` and `select` platforms to enable writing to the inverter (EMS mode, SOC limits, Charge/Discharge power).
- [ ] Add support for scheduling via Time of Use registers.

## 🤝 Contributing & Help Welcome!
This is an open-source community project, and **help is always welcome!** Whether you want to add more Modbus registers, improve the code, fix a bug, or translate the integration into more languages: feel free to fork the repository and open a Pull Request.

## 🐛 Troubleshooting & Support
If the integration fails to connect, check your Home Assistant logs (`home-assistant.log`). 
Common issues:
- `Connection refused`: Another device or script is already connected to the inverter's Modbus port.
- `Timeout`: Poor WiFi signal to the inverter dongle.

Feel free to open an issue on this repository if you encounter any bugs!

---
*Disclaimer: This is a community-built integration and is not officially affiliated with or endorsed by Pylontech.*
