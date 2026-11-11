Attribute VB_Name = "Sheet1"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True

Private Sub Worksheet_Change(ByVal Target As Range)
    Dim cell As Range
    For Each cell In Target
        If Not Intersect(cell, Range("K27")) Is Nothing Then
            If IsEmpty(cell.Value) Then
                Application.EnableEvents = False
                cell.Value = "|Z|-Theta" ' Valeur par défaut
                Application.EnableEvents = True
            End If
        End If
        If Not Intersect(cell, Range("K28")) Is Nothing Then
            If IsEmpty(cell.Value) Then
                Application.EnableEvents = False
                cell.Value = 400 ' Valeur par défaut
                Application.EnableEvents = True
            End If
        End If
        If Not Intersect(cell, Range("K29")) Is Nothing Then
            If IsEmpty(cell.Value) Then
                Application.EnableEvents = False
                cell.Value = 100  ' Valeur par défaut
                Application.EnableEvents = True
            End If
        End If
        If Not Intersect(cell, Range("K30")) Is Nothing Then
            If IsEmpty(cell.Value) Then
                Application.EnableEvents = False
                cell.Value = 15000000# ' Valeur par défaut
                Application.EnableEvents = True
            End If
        End If
        If Not Intersect(cell, Range("K31")) Is Nothing Then
            If IsEmpty(cell.Value) Then
                Application.EnableEvents = False
                cell.Value = True ' Valeur par défaut
                Application.EnableEvents = True
            End If
        End If
    Next cell
End Sub

