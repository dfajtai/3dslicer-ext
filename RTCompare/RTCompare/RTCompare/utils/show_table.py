import pandas as pd
import qt


def populate_qtablewidget_with_dataframe(dataframe, table_widget, columns, resize = True):
    """
    Populate a QTableWidget with selected columns from a pandas DataFrame.

    Args:
        dataframe (pd.DataFrame): The DataFrame containing the data.
        table_widget (QTableWidget): The QTableWidget to populate.
        columns (list of str): List of column names to display in the QTableWidget.
    """
    # Filter the DataFrame to include only the specified columns
    df_filtered = dataframe[columns]

    # Set up the QTableWidget dimensions
    table_widget.setRowCount(len(df_filtered))
    table_widget.setColumnCount(len(columns))
    table_widget.setHorizontalHeaderLabels(columns)

    # Populate the QTableWidget with DataFrame values
    for row in range(len(df_filtered)):
        for col, column_name in enumerate(columns):
            item = qt.QTableWidgetItem(str(df_filtered.iloc[row, col]))
            table_widget.setItem(row, col, item)
            
    if len(columns) ==1:
        header = table_widget.horizontalHeader()       
        header.setSectionResizeMode(0, qt.QHeaderView.ResizeToContents)
    elif resize:
        header = table_widget.horizontalHeader()
        for c in range(len(columns)):
            header.setSectionResizeMode(c, qt.QHeaderView.ResizeToContents)