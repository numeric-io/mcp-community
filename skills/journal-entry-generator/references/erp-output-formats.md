# ERP output formats

The JE generation, balancing, and workpaper are ERP-neutral. Only the **output**
differs per ERP: the import-file layout, and whether a direct post is available.

Generate a **canonical JE** first, then map it to the target ERP's format.

## Canonical JE model

```json
{
  "external_id": "JE-ACM-202602-CLOSEAP-001",
  "date": "2026-02-28",
  "memo": "[Task #tsk_xxx] Close AP",
  "entity": "Acme Corp US",          // subsidiary / company / org
  "lines": [
    {
      "account": "6122",              // GL account number or code
      "debit": 149345.38,
      "credit": null,
      "memo": "Salaries — 45 employees",
      "name": null,                   // customer/vendor/employee (req. on AR/AP lines)
      "department": "520",
      "location": null,
      "class": null
    }
  ]
}
```

Invariant for every ERP: **Σ debit == Σ credit** (validate before emitting).

Pick the target ERP from the task's saved `## JE Instructions` (`Target ERP:`),
otherwise ask the user. Default to NetSuite only if a prior run set it.

---

## NetSuite

- **Direct post:** YES — `ns_createRecord` with record type `journalentry`. See SKILL.md Phase 3.
- **Import file:** CSV with `Journal Entry -Line:` prefixes for the Import Assistant.
- **Field detail:** [netsuite-je-schema.md](netsuite-je-schema.md). Errors: [ns-posting-errors.md](ns-posting-errors.md).
- Dimensions: `subsidiary` (header), `department` / `location` / `class` (line).

## QuickBooks Online

- **Direct post:** Not available through the connected MCP (no JE-create tool). Output a file / use the QBO API.
- **No native UI CSV import for JEs** — accountants post via the **QBO Accounting API `JournalEntry`** object, or a third-party importer (SaasAnt, Autymate, Zed). Emit a CSV those importers accept *and* note the API shape.
- **Importer CSV columns:** `JournalNo` (DocNumber — same value groups lines into one JE), `JournalDate`, `Account`, `Debit`, `Credit`, `Description` (line memo), `Name` (entity), `Class`, `Location`.
- **API `JournalEntry`:** `DocNumber`, `TxnDate`, and a `Line[]` where each line is `JournalEntryLineDetail` with `PostingType` (`Debit`|`Credit`), `AccountRef`, `Amount`, optional `Entity` / `ClassRef` / `DepartmentRef`.
- **Hard rule:** lines hitting **AR or AP accounts must carry a `Name`/`Entity`** (customer for AR, vendor for AP) or QBO rejects the entry.
- Source: https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/journalentry

## Xero

- **Direct post:** Not available through the connected MCP. Output a file (native import) or use the API.
- **Native Manual Journal CSV import** (Accounting → Manual journals → Import). Download Xero's template and fill it.
- **CSV columns:** `Narration`, `Date`, `Description`, `AccountCode` (must match the Xero chart of accounts), `Debit`, `Credit`. Tracking categories go in extra named columns.
- **Multi-line journals:** leave `Date` **and** `Narration` blank on a continuation row and Xero attaches it to the journal above. First row of each journal carries the date + narration.
- **Limit:** up to 300 lines per file. API alternative: `ManualJournals` endpoint.
- Source: https://central.xero.com/s/article/Add-import-and-post-manual-journals-US

## Sage Intacct

- **Direct post:** Not available through the connected MCP. Output a file (Import Service / CSV) or use the API.
- **Company-specific template.** Dimensions vary per company, so the canonical move is to **download the GL Journal Entries template from the user's own Intacct instance** (Company → Setup → Import data) and fill it — don't hardcode a universal column set.
- **Structure:** header fields (transaction `DATE`, `JOURNAL` symbol, `DESCRIPTION`) + line rows. Each line: `LINE_NO` (preserves order), GL `ACCT_NO`, debit/credit `AMOUNT`, and any in-use dimensions (`LOCATION_ID`, `DEPT_ID`, etc.).
- Required fields reference records by **ID** (account number, journal symbol).
- Source: https://www.intacct.com/ia/docs/en_US/help_action/More/ImportService/importservice-GL/importservice-GL-journal-entries.htm

---

## Mapping the canonical JE → each ERP

| Canonical | NetSuite | QuickBooks Online | Xero | Sage Intacct |
|-----------|----------|-------------------|------|--------------|
| external_id | `externalid` | `DocNumber`/`JournalNo` | (narration ref) | doc/ref field |
| date | `trandate` | `TxnDate`/`JournalDate` | `Date` | `DATE` |
| entity | `subsidiary` | company file | org | top-level entity |
| account | `account` | `AccountRef`/`Account` | `AccountCode` | `ACCT_NO` |
| debit/credit | `debit`/`credit` | `PostingType`+`Amount` / `Debit`+`Credit` | `Debit`/`Credit` | `AMOUNT` (+sign/col) |
| memo | line `memo` | `Description` | `Description` | line description |
| name | (entity on line) | `Name`/`Entity` (req. AR/AP) | n/a | n/a |
| department/location/class | `department`/`location`/`class` | `DepartmentRef`/`ClassRef` | tracking categories | `DEPT_ID`/`LOCATION_ID` |

When unsure of an ERP's exact template (especially Sage's company-specific
dimensions, or which third-party importer a QBO user runs), **ask the user to
share their import template** and map the canonical JE onto its columns rather
than guessing.
