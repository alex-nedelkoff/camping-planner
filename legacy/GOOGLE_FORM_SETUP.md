# Google Form Setup — Camping Trip Planner

## Create the Form

Go to [Google Forms](https://forms.google.com) and create a new form.

The form uses **section branching** to show different park options based on
how far people are willing to drive from Ajax.

---

### Section 1: Basics

**1. Name** (Short answer, required)

**2. What days of the week generally work for you?** (Checkboxes, required)
Description: "Select all that apply"
- Monday
- Tuesday
- Wednesday
- Thursday
- Friday
- Saturday
- Sunday

**3. Available Date Ranges** (Checkbox grid)
- **Rows**: Weekend date ranges you're considering (e.g., "Jul 3-5", "Jul 10-12", "Jul 17-19")
- **Columns**: "Available", "Maybe", "Unavailable"
- Or simpler: use **Checkboxes** listing each weekend and let people check the ones they're free

**4. Are you okay with driving more than 3 hours from Ajax?** (Multiple choice, required)
- Yes — show me all parks (up to 5 hrs)
- No — only parks within 3 hours

> **Set up branching:** Click the three-dot menu on this question → "Go to section based on answer"
> - "Yes" → Go to **Section 2A: All Parks (0-5 hrs)**
> - "No" → Go to **Section 2B: Closer Parks (under 3 hrs)**

---

### Section 2A: All Parks (0-5 hrs from Ajax)

**5a. Preferred Parks** (Checkboxes, select all that apply)

*Under 2 hours:*
- Darlington (~15 min)
- Sibbald Point (~45 min)
- Balsam Lake (~1.25 hrs)
- Presqu'ile (~1.75 hrs)
- Wasaga Beach (~1.75 hrs)

*2-3 hours:*
- Awenda (~2 hrs)
- Silent Lake (~2 hrs)
- Kawartha Highlands (~2.25 hrs — backcountry/canoe)
- Sandbanks (~2.25 hrs)
- Bon Echo (~2.5 hrs)
- Long Point (~2.5 hrs)

*3-5 hours:*
- Frontenac (~3 hrs — backcountry)
- Arrowhead (~3 hrs)
- Killbear (~3 hrs)
- Pinery (~3.25 hrs)
- Grundy Lake (~3.25 hrs)
- MacGregor Point (~3.25 hrs)
- Algonquin - Canisbay Lake (~3.5 hrs)
- Algonquin - Pog Lake (~3.5 hrs)
- Algonquin - Mew Lake (~3.5 hrs)
- Algonquin - Lake of Two Rivers (~3.5 hrs)
- Algonquin - Rock Lake (~3.5 hrs)
- Rondeau (~3.5 hrs)
- French River (~3.75 hrs)
- Killarney (~4.5 hrs)
- Pancake Bay (~4.75 hrs)
- Other (with text field)

> After this section → Go to **Section 3: Gear & Other**

---

### Section 2B: Closer Parks (under 3 hrs from Ajax)

**5b. Preferred Parks** (Checkboxes, select all that apply)

*Under 2 hours:*
- Darlington (~15 min)
- Sibbald Point (~45 min)
- Balsam Lake (~1.25 hrs)
- Presqu'ile (~1.75 hrs)
- Wasaga Beach (~1.75 hrs)

*2-3 hours:*
- Awenda (~2 hrs)
- Silent Lake (~2 hrs)
- Kawartha Highlands (~2.25 hrs — backcountry/canoe)
- Sandbanks (~2.25 hrs)
- Bon Echo (~2.5 hrs)
- Long Point (~2.5 hrs)
- Other (with text field)

> After this section → Go to **Section 3: Gear & Other**

---

### Section 3: Gear & Other

**6. Gear You Can Bring** (Checkboxes)
- Tent (fits ___ people) — use "Other" for count
- Stove / cooking setup
- Cooler
- Tarp / shelter
- Water filter
- First aid kit
- Canoe / kayak
- Other

**7. Dietary Restrictions** (Short answer, optional)
Placeholder: "Vegetarian, nut allergy, etc."

**8. Notes** (Paragraph, optional)
For anything else — ride sharing, gear requests, etc.

---

## Sharing Results via Google Sheet

Since you want friends to see everyone's responses in the sheet:

### 1. Link the form to a sheet
1. In the form editor, click the **Responses** tab
2. Click the green Sheets icon → "Create a new spreadsheet"
3. Name it "Camping Trip Responses"

### 2. Create a clean summary view
The raw response sheet will have separate columns for 5a and 5b (since they're
different questions). To make it readable:

1. Add a new tab called **"Summary"**
2. Use formulas to merge the two park preference columns:
   ```
   =IF(A2="Yes", E2, F2)
   ```
   (where E = Section 2A parks, F = Section 2B parks — adjust column letters to match your actual sheet)
3. Add conditional formatting to highlight the most popular dates/parks

### 3. Share the sheet
1. Click **Share** on the spreadsheet
2. Set to "Anyone with the link can view"
3. Add the sheet link to the form's confirmation message:
   - Form Settings (gear icon) → **Presentation** → **Confirmation message**
   - Add: "See everyone's responses here: [sheet link]"

This way respondents land on the results right after submitting.

---

## Set Up API Access (optional — for reading responses programmatically)

Only needed if you want to use `sheet_reader.py` to pull/summarize responses.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use existing)
3. Enable the **Google Sheets API**
4. Create a **Service Account** under APIs & Services → Credentials
5. Download the JSON key file → save as `credentials.json` in this project folder
6. Share your Google Sheet with the service account email (found in credentials.json)

Then run: `python3 sheet_reader.py "Camping Trip Responses"`
