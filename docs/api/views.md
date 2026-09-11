# Views

Immutable navigation, result, detail, status, and selection models rendered by the workbench. The [page guide](../pages.md#design-the-page-around-a-question) maps information shapes to useful views.

## Paginated tables

Use `Pagination` when a page owns a bounded query result and needs to expose the result's position without making pagination a database or workbench concern:

```python
pagination = Pagination(page=2, page_size=20, total_items=41)
view = TableView(
    title="Mapping review",
    columns=("Source", "Status"),
    rows=rows,
    pagination=pagination,
    actions=pagination_actions(pagination),
)
```

`pagination_actions` supplies disabled-aware previous/next commands. The page still owns the handlers and the query; Groundskeeping only renders the metadata and stable table chrome.

`TableRow.key` remains the stable row identity. Pages can use it to handle a selected row, open a wizard, or apply a later validation/acceptance action. The base `TableView` intentionally does not embed editable controls, so adding a specialised row editor later will not change the existing table or pagination contract.

::: groundskeeping.contracts.views
