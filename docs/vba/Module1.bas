Attribute VB_Name = "Module1"
Option Explicit

Public rm As VisaComLib.ResourceManager
Public instrument As VisaComLib.FormattedIO488

Global Const COLOR_RED = 3                              'Color is red.
Global Const COLOR_BLUE = 5                             'Color is blue.

Private xData() As Double                               'xData array.



' ==========================================
' Foster RL (series) + optional parallel Rp/Cp branches
' Data source: Sheet1 (index 1)
'   Col A: f(Hz), Col B: Ls(H), Col C: Rs(Ohm)
'
' MATLAB equivalence:
'   local_Zseries(w, R0, L0, RL)
'   local_Ztotal(w, x, NR, NC)
'   local_residual(...)
' ==========================================

' ---------- Modeler settings ----------
Private Const NR_MIN As Long = 1
Private Const NR_MAX As Long = 3

Private Const NC_MIN As Long = 1
Private Const NC_MAX As Long = 2

' Bounds (soft clamp, because Nelder-Mead is unconstrained)
Private Const RP_MAX As Double = 1000000000#
Private Const CP_MAX As Double = 0.000001

' ---------- Globals for objective ----------
Private gW() As Double
Private gF() As Double
Private gZre() As Double
Private gZim() As Double
Private gN As Long
Private gNR As Long
Private gNC As Long

' ===========================
'   Complex helper (minimal)
' ===========================
Private Type Complex
    re As Double
    im As Double
End Type


'===================================
' 4194A Step1
'===================================
Sub Step1()

    Dim strAddr         As String
    Dim strRes          As String
    
    On Error GoTo ErrorHandler
    
    Range("C22").Value = vbNullString
    Range("D22").Value = vbNullString
    
    strAddr = setAddrString
    
    If setVisaCom(strAddr) Then
        ' Remplacer *IDN? par une commande compatible avec le 4194A
        strRes = cmdGet("REV?") ' ou "ID?" si disponible
        Range("C22").Select
        Selection.Font.ColorIndex = COLOR_BLUE
        Range("C22").Value = "OK"
        Range("D22").Value = strRes
        If Sheets(1).Cells(15, 3).Value = "GPIB" Then
            execLocal (strAddr)
        End If
    Else
        Range("C22").Select
        Selection.Font.ColorIndex = COLOR_RED
        Range("C22").Value = "ERROR"
        Range("D22").Value = "Configuration Error."
        Exit Sub
    End If
    
    Exit Sub

    '===================================
    ' ErrorHandler
    '===================================
ErrorHandler:
    ' Display the error message
    MsgBox "*** Error : " + Error$, vbExclamation
    End
End Sub

'===================================
' 4194A Step2 (Get Data)
'===================================
Sub Step2_GetData()
    Dim strAddr         As String
    Dim strSheetName    As String
    Dim cnt             As Integer
    
    On Error GoTo ErrorHandler

    Sheets(1).Cells(34, 3) = vbNullString                                       'Clear the cell of error message.
    strSheetName = "MasterSheet"
    If Not ExistSheet(strSheetName, cnt) Then                                   'Check the master sheet.
        Sheets(1).Cells(34, 3) = "MasterSheet not found."
        Exit Sub
    End If
    
    strSheetName = Sheets(1).Cells(29, 3)
    If Not ExistSheet(strSheetName, cnt) Then                                   'Check the sheet name.
        If Not CreateExcelSheet(strSheetName) Then                              'Create the excel sheet.
            Sheets(1).Cells(34, 3) = "Invalid Excel Sheet Name."                'Display the error message.
            Exit Sub
        End If
    Else
        Sheets(1).Cells(34, 3) = "Duplicated Sheet Name."                       'Display the error message.
        Exit Sub
    End If
    
    strAddr = setAddrString
    
    '===================================
    ' Open Instrument
    '===================================
    If setVisaCom(strAddr) Then
        Sheets(1).Cells(32, 4) = "Please wait..."
        GetSettings
        GetMeasData
        MakeChart (strSheetName)
        If Sheets(1).Cells(15, 3).Value = "GPIB" Then
            execLocal (strAddr)                                                     'Send local command.
        End If
        Sheets(1).Cells(32, 4) = vbNullString
        Sheets(1).Cells(32, 5) = vbNullString
    End If
    
    Exit Sub
    '===================================
    ' ErrorHandler
    '===================================
ErrorHandler:
    ' Display the error message
    MsgBox "*** Error : " + Error$, vbExclamation
    If Cells(15, 3).Value = "GPIB" Then
        execLocal (strAddr)                                                         'Send local command.
    End If
    Sheets(1).Cells(32, 4) = vbNullString
    End
End Sub

Function setVisaCom(strAddr As String) As Boolean
    On Error GoTo setVisaCom_Err
    
    setVisaCom = False
    Set rm = New VisaComLib.ResourceManager                 'Instantiate the GRM (Global Resource Manager) object
    Set instrument = New VisaComLib.FormattedIO488          'Set "instrument" as object for VisaComLib.FormattedIO488
    Set instrument.IO = rm.Open(strAddr)                    'Instantiate "instrument" before using Open method through IO property
    
    instrument.IO.Timeout = 30000
    instrument.IO.TerminationCharacterEnabled = True
    setVisaCom = True
    Exit Function
    
setVisaCom_Err:

End Function
Function setAddrString() As String

    setAddrString = vbNullString
    Select Case Cells(15, 3).Value
        Case "GPIB"
            setAddrString = "GPIB0::" & Cells(17, 3).Value & "::INSTR"                'GPIB address string.
        Case "LAN"
            setAddrString = "TCPIP0::" & Cells(17, 3).Value & "::5025::SOCKET"        'LAN address string.
        Case Else
            setAddrString = vbNullString
    End Select

End Function
Function CreateExcelSheet(strName As String) As Boolean
    Dim vStr As Variant
    
    On Error GoTo CreateExcelSheet_Error
    
    CreateExcelSheet = False
    
    Sheets("MasterSheet").Copy After:=Sheets(Sheets.Count)                      'Copy the master sheet to after the last sheet.
    
    Sheets(ActiveSheet.Name).Name = strName                                     'Rename the copied sheet name.
    Sheets(1).Select                                                            'Select the sheet(1).
    
    CreateExcelSheet = True
    Exit Function
CreateExcelSheet_Error:
    Application.DisplayAlerts = False                                           'Hidden warning window.
    ActiveSheet.Delete                                                          'Delete the copied sheet.
    Sheets(1).Select                                                            'Select the sheet(1).
    Application.DisplayAlerts = True                                            'Available warning window.
End Function
Function ExistSheet(strName As String, iNo As Integer) As Boolean
    Dim i, cnt As Integer
    
    ExistSheet = False
    For i = 1 To Sheets.Count
        If Sheets(i).Name = strName Then
            ExistSheet = True
            Exit For
        End If
    Next i
    iNo = i
End Function

Function GetSettings()
    Dim cnt As Integer
    Dim strRes As String
    Dim strMeasType As String
    Dim lNop As Long
    Dim startFreq As String
    Dim stopFreq As String
    Dim numPoints As String
    Dim sweeplog As Boolean
    Dim sweepType As String
    Dim measType As String
    Dim i_mode As Integer
    Dim integType As String
    Dim i_integ As Integer
    
      
    cnt = Sheets.Count
    'variables inutiles mais facilitant la relecture !
    measType = CStr(Sheets(1).Cells(27, 11).Value)    ' Type de mesure     K27
    numPoints = CStr(Sheets(1).Cells(28, 11).Value)   ' Nombre de points    K28
    startFreq = CStr(Sheets(1).Cells(29, 11).Value)   ' Fréquence de départ K29
    stopFreq = CStr(Sheets(1).Cells(30, 11).Value)    ' Fréquence de fin    K30
    sweeplog = CBool(Sheets(1).Cells(31, 11).Value)   ' Balayage log        K31
    integType = CStr(Sheets(1).Cells(32, 11).Value)   ' Temps d'intégration K32
   
   
    With Sheets(cnt)
        
        Select Case measType
            Case "|Z|-Theta":           i_mode = 1
            Case "R-X":                 i_mode = 2
            Case "Ls-Rs":               i_mode = 3
            Case "Ls-Q":                i_mode = 4
            Case "Cs-Rs":               i_mode = 5
            Case "Cs-Q":                i_mode = 6
            Case "Cs-D":                i_mode = 7
            Case "|Y|-Theta":           i_mode = 8
            Case "G-B":                 i_mode = 9
            Case "Lp-G":                i_mode = 10
            Case "Lp-Q":                i_mode = 11
            Case "Cp-G":                i_mode = 12
            Case "Cp-Q":                i_mode = 13
            Case "Cp-D":                i_mode = 14
            Case "|Z|-Ls":              i_mode = 15
            Case "|Z|-Cs":              i_mode = 16
            Case "|Z|-Lp":              i_mode = 17
            Case "|Z|-Cp":              i_mode = 18
            Case "Lp-Rp":               i_mode = 19
            Case "Cp-Rp":               i_mode = 20
            Case Else
                i_mode = -1
                .Range("D4").Value = "Error"
        End Select
        .Range("D7").Value = integType
        Select Case integType
            Case "500µsec":             i_integ = 1
            Case "1msec":               i_integ = 2
            Case "100msec":             i_integ = 3
            Case Else
                i_integ = -1
                .Range("D7").Value = "Error"
        End Select
        
        If sweeplog = True Then
            sweepType = "SWT2"
            .Range("D5").Value = "Log"
        Else
            sweepType = "SWT1"
            .Range("D5").Value = "Linear"
        End If

            '------ Configuration de la mesure ------
        cmdSet "FNC1"                    ' Fonction Impédance
        cmdSet sweepType                 ' Balayage linéaire
        cmdSet "NOP=" & numPoints        ' Nombre de points
        cmdSet "START=" & startFreq      ' Fréquence de départ
        cmdSet "STOP=" & stopFreq        ' Fréquence de fin
        cmdSet "SWTRG"                   ' Déclenchement de la mesure
        cmdSet "TRIG"                    ' Déclenchement de la mesure
        
        '--- Date & Heure
        .Range("B1").Value = Now

        '--- Informations générales
        .Range("B2").Value = "HP 4194A (IDN non supporté)"

        '--- Fonction de mesure
        cmdSet "FNC1" ' Impédance seulement (le DC-bias et Gain-phase ne sont pas gérés)
        
        .Range("D3").Value = measType
        .Range("L5").Value = Split(measType, "-")(0)
        .Range("L6").Value = Split(measType, "-")(1)
        .Range("D6").Value = numPoints
        .Range("D10").Value = "Data Trace " & Split(measType, "-")(0)
        .Range("E10").Value = "Data Trace " & Split(measType, "-")(1)
        
        cmdSet "ITM" & CStr(i_integ)    'Réglage du temps d'intégration
        cmdSet "IMP" & CStr(i_mode)     'Envoi de la dm
        
        
    End With
End Function



Function GetMeasData()
    Dim i As Integer
    Dim cnt As Integer
    Dim lNop As Long
    Dim strA As String
    Dim strB As String
    Dim strX As String
    Dim vA As Variant
    Dim vB As Variant
    Dim vX As Variant
    Dim integType As String
    Dim i_integ As Integer
    Dim time As Integer
    Dim myTime As String
    Dim numPoints As Integer
    Dim quantum As Variant
    Dim varTot, varSec, varMin As Variant
    
    quantum = Array(0.5 * 0.001, 1 * 0.001, 11 * 0.001)
    integType = CStr(Sheets(1).Cells(32, 11).Value)         ' Temps d'intégration K32
    numPoints = CInt(Sheets(1).Cells(28, 11).Value)         ' Nombre de points    K28
                
    
    Select Case integType
        Case "500µsec":             i_integ = 1
        Case "1msec":               i_integ = 2
        Case "100msec":             i_integ = 3
        Case Else
                i_integ = -1
                Sheets(1).Range("D4").Value = "Error"
    End Select
    
    varTot = 50 * numPoints * quantum(i_integ - 1)
    varMin = Application.WorksheetFunction.Floor_Math(varTot / 60, 1)
    varSec = varTot - varMin * 60
    myTime = "0:0" & CStr(varMin) & ":" & CStr(varSec) 'gestion du temps d'attente en fonction du temps d'intégration 3.3 minutes pour 400point @ 100ms
    Sheets(1).Cells(32, 5) = CStr(varTot) & "secondes" 'affichage du temps d'attente
    
    cnt = Sheets.Count
    With Sheets(cnt)
        
        '------ Lecture des données ------
        Application.Wait (Now + TimeValue(myTime)) ' Attends 8 seconds que la mesure soit réalisée
        strX = cmdGet("X?") ' Valeurs Y (données mesurées)
        Application.Wait (Now + TimeValue("0:00:01")) ' Attends 1 seconds que la mesure soit réalisée
        strA = cmdGet("A?") ' Valeurs X (fréquences)
        Application.Wait (Now + TimeValue("0:00:01")) ' Attends 1 seconds que la mesure soit réalisée
        strB = cmdGet("B?") ' Valeurs Y (données mesurées)
        
        vA = Split(Replace(Replace(strA, Chr(10), ""), Chr(13), ""), ",")
        vB = Split(Replace(Replace(strB, Chr(10), ""), Chr(13), ""), ",")
        vX = Split(Replace(Replace(strX, Chr(10), ""), Chr(13), ""), ",")

        lNop = UBound(vX) + 1

        For i = 1 To lNop
            .Range("B" & 10 + i) = i
            .Range("C" & 10 + i) = vX(i - 1)
            .Range("D" & 10 + i) = vA(i - 1)
            .Range("E" & 10 + i) = vB(i - 1)
        Next i
    End With
End Function


Function MakeChart(strSheetName As String)

    Dim i           As Integer
    Dim lNop        As Long
    Dim strMeas     As String
    Dim cnt         As Integer
    Dim strRange    As String
    Dim strGname    As String

    Dim r1 As Range
    Dim R2 As Range
    
    lNop = Sheets(1).Cells(28, 11).Value
    strMeas = Sheets(1).Cells(3, 4).Value
    cnt = Sheets.Count
    
    Sheets(cnt).Select
    If strMeas <> "COMP" Then
        ActiveSheet.ChartObjects(1).Activate
        With ActiveChart
            .SeriesCollection(1).XValues = Sheets(cnt).Range("N11:N" & lNop + 10)
            .SeriesCollection(1).Values = Sheets(cnt).Range("D11:D" & lNop + 10)
            .SeriesCollection(2).XValues = Sheets(cnt).Range("N11:N" & lNop + 10)
            .SeriesCollection(2).Values = Sheets(cnt).Range("E11:E" & lNop + 10)
            .ChartTitle.Text = Sheets(cnt).Range("D3")
            .Axes(xlValue, xlSecondary).Select
        End With
        Selection.TickLabelPosition = xlNextToAxis                           'Displays X-axis 2nd label.
        Range("A1").Select
    Else
        For i = 1 To 2
            If i = 1 Then
                strRange = "D11:E"
            Else
                strRange = "F11:G"
            End If
            Range(strRange & lNop + 10).Select
            Charts.Add
            ActiveChart.ChartType = xlXYScatterLinesNoMarkers
            ActiveChart.SetSourceData Source:=Sheets(strSheetName).Range(strRange & lNop + 10), PlotBy _
                :=xlColumns
            ActiveChart.Location Where:=xlLocationAsObject, Name:=strSheetName
            
            With ActiveChart
                .HasTitle = True                                            'Graph tytle to on.
                .HasLegend = False                                          'Graph legend to off.
                If i = 1 Then
                    .ChartTitle.Characters.Text = "Complex Z"
                Else
                    .ChartTitle.Characters.Text = "Complex Y"
                End If
                .Axes(xlCategory, xlPrimary).HasTitle = True
                .Axes(xlCategory, xlPrimary).AxisTitle.Characters.Text = "Real"
                .Axes(xlValue, xlPrimary).HasTitle = True
                .Axes(xlValue, xlPrimary).AxisTitle.Characters.Text = "Imag"
            End With
            '----------------------
            ' X-axis
            '----------------------
            With ActiveChart.Axes(xlCategory)                               'X-axis.
                .HasMajorGridlines = True                                   '
                .HasMinorGridlines = False                                  '
                .MinimumScaleIsAuto = True                                  '
                .MaximumScaleIsAuto = True                                  '
                .MinorUnitIsAuto = True                                     '
                .MajorUnitIsAuto = True                                     '
                .Crosses = xlCustom                                         '
                .CrossesAt = .MinimumScale                                  '
                .ReversePlotOrder = False                                   '
                .ScaleType = xlLinear                                       'Scale type to linear.
                .DisplayUnit = xlNone                                       '
            End With
            With Selection.Border
                .ColorIndex = 16
                .Weight = xlHairline
                .LineStyle = xlContinuous
            End With
            '----------------------
            ' Y-axis
            '----------------------
            With ActiveChart.Axes(xlValue)                                  'Y-axis.
                .HasMajorGridlines = True                                   '
                .HasMinorGridlines = False                                  '
                .MinimumScaleIsAuto = True                                  '
                .MaximumScaleIsAuto = True                                  '
                .MinorUnitIsAuto = True                                     '
                .MajorUnitIsAuto = True                                     '
                .Crosses = xlCustom                                         '
                .CrossesAt = .MinimumScale                                  '
                .ReversePlotOrder = False                                   '
                .ScaleType = xlLinear                                       'Scale type to linear.
                .DisplayUnit = xlNone                                       '
            End With
            With Selection.Border
                .ColorIndex = 16
                .Weight = xlHairline
                .LineStyle = xlContinuous
            End With
        Next i
        
        '------------------------
        ' Delete default chart.
        '------------------------
        ActiveSheet.ChartObjects(1).Activate
        ActiveChart.Parent.Delete
    
        '---------------------------
        ' Move chart around.
        '---------------------------
        With ActiveSheet
            '--- Chart 1 ---
            With .ChartObjects(1)
                .Activate
                .Top = ActiveSheet.Range("B31").Top
                .Left = ActiveSheet.Range("B31").Left
                .Height = 280
                .Width = 450
            End With
            ActiveChart.Axes(xlCategory).Select
            Selection.TickLabels.NumberFormatLocal = "0.00"
            ActiveChart.Axes(xlValue).Select
            Selection.TickLabels.NumberFormatLocal = "0.00E+00"
            '--- Chart 2 ---
            With .ChartObjects(2)
                .Activate
                .Top = ActiveSheet.Range("J31").Top
                .Left = ActiveSheet.Range("J31").Left
                .Height = 280
                .Width = 450
            End With
            ActiveChart.Axes(xlCategory).Select
            Selection.TickLabels.NumberFormatLocal = "0.00"
            ActiveChart.Axes(xlValue).Select
            Selection.TickLabels.NumberFormatLocal = "0.00E+00"
        End With
        Range("A1").Select
    End If
    
    Sheets(1).Select

End Function

Function cmdSet(sCmd As String)
    Dim lRet As Long
    
    instrument.WriteString sCmd

End Function
Function cmdGet(sCmd As String) As String
    Dim str  As String
    
    cmdGet = vbNullString
    str = vbNullString
    
    instrument.WriteString sCmd
    str = instrument.ReadString()
    cmdGet = Left(str, Len(str) - 1)                'Control code (Lf) omitting.

End Function
Sub execLocal(strAddr As String)
    Dim gpib As IGpib
    
    On Error GoTo execLocal_Err
    
    Set gpib = rm.Open(strAddr)
    gpib.ControlREN (GPIB_REN_GTL)                  'Send local command.
    gpib.Close
    
execLocal_Err:

End Sub




' RL foster modelisation


Private Function Cx(ByVal re As Double, ByVal im As Double) As Complex
    Cx.re = re: Cx.im = im
End Function

Private Function CAdd(a As Complex, b As Complex) As Complex
    CAdd = Cx(a.re + b.re, a.im + b.im)
End Function

Private Function CSub(a As Complex, b As Complex) As Complex
    CSub = Cx(a.re - b.re, a.im - b.im)
End Function

Private Function CMul(a As Complex, b As Complex) As Complex
    CMul = Cx(a.re * b.re - a.im * b.im, a.re * b.im + a.im * b.re)
End Function

Private Function CDiv(a As Complex, b As Complex) As Complex
    Dim den As Double
    den = b.re * b.re + b.im * b.im
    If den <= 0# Then
        CDiv = Cx(0#, 0#)
    Else
        CDiv = Cx((a.re * b.re + a.im * b.im) / den, (a.im * b.re - a.re * b.im) / den)
    End If
End Function

Private Function CInv(a As Complex) As Complex
    Dim den As Double
    den = a.re * a.re + a.im * a.im
    If den <= 0# Then
        CInv = Cx(0#, 0#)
    Else
        CInv = Cx(a.re / den, -a.im / den)
    End If
End Function

Private Function CAbs(a As Complex) As Double
    CAbs = Sqr(a.re * a.re + a.im * a.im)
End Function

Private Function CAngle(a As Complex) As Double
    ' atan2(im,re)
    CAngle = WorksheetFunction.Atan2(a.im, a.re)
End Function

' ===========================
'   Model functions
' ===========================
Private Function ZParallelRL(ByVal w As Double, ByVal R As Double, ByVal L As Double) As Complex
    ' Z = (j*w*L*R)/(R + j*w*L)  (identique MATLAB)
    Dim jwL As Complex, num As Complex, den As Complex
    jwL = Cx(0#, w * L)
    num = CMul(Cx(R, 0#), jwL)
    den = CAdd(Cx(R, 0#), jwL)
    ZParallelRL = CDiv(num, den)
End Function

Private Function ZFosterSeries_RL(ByVal w As Double, ByRef x() As Double, ByVal NR As Long) As Complex
    ' local_Zseries(w,R0,L0,RL)
    Dim z As Complex
    Dim k As Long, Rk As Double, Lk As Double

    z = Cx(x(1), w * x(2)) ' R0 + j*w*L0

    For k = 1 To NR
        Rk = x(2 + 2 * k - 1)
        Lk = x(2 + 2 * k)
        z = CAdd(z, ZParallelRL(w, Rk, Lk))
    Next k

    ZFosterSeries_RL = z
End Function

Private Function ZFosterTotal_RL_RpCp(ByVal w As Double, ByRef x() As Double, ByVal NR As Long, ByVal NC As Long) As Complex
    ' local_Ztotal(w,x,NR,NC)
    Dim Zs As Complex
    Zs = ZFosterSeries_RL(w, x, NR)

    If NC = 0 Then
        ZFosterTotal_RL_RpCp = Zs
        Exit Function
    End If

    Dim base As Long: base = 2 + 2 * NR
    Dim m As Long
    Dim Yp As Complex: Yp = Cx(0#, 0#)

    For m = 1 To NC
        Dim Rp As Double, Cp As Double, G As Double
        Rp = x(base + 2 * m - 1)
        Cp = x(base + 2 * m)

        ' MATLAB: (Rp>0)/max(Rp,eps)
        If Rp > 0# Then
            If Rp < 1E-300 Then
                G = 1E+300
            Else
                G = 1# / Rp
            End If
        Else
            G = 0#
        End If

        Yp = CAdd(Yp, Cx(G, w * Cp)) ' G + j*w*Cp
    Next m

    ' Zt = 1 / (1/Zs + Yp)
    Dim invZs As Complex
    invZs = CInv(Zs)
    ZFosterTotal_RL_RpCp = CInv(CAdd(invZs, Yp))
End Function

' ===========================
'   Residual (as MATLAB)
'   r = [Re(Zm-Z)/sc ; Im(Zm-Z)/sc], sc=max(1e-6,|Z|)
'   We minimize sum(r.^2) => SSR
' ===========================
Private Function ObjSSR(ByRef x() As Double) As Double
    Dim i As Long
    Dim zmod As Complex, zdat As Complex, dz As Complex
    Dim sc As Double
    Dim ss As Double, rr As Double, ii As Double

    ' clamp for passivity + reasonable bounds
    Call ClampParams(x, gNR, gNC)

    ss = 0#
    For i = 1 To gN
        zmod = ZFosterTotal_RL_RpCp(gW(i), x, gNR, gNC)
        zdat = Cx(gZre(i), gZim(i))
        dz = CSub(zmod, zdat)

        sc = CAbs(zdat)
        If sc < 0.000001 Then sc = 0.000001

        rr = dz.re / sc
        ii = dz.im / sc
        ss = ss + rr * rr + ii * ii
    Next i

    ObjSSR = ss
End Function

Private Sub ClampParams(ByRef x() As Double, ByVal NR As Long, ByVal NC As Long)
    Dim i As Long
    For i = 1 To UBound(x)
        If x(i) < 0# Then x(i) = 0#
    Next i

    If NC > 0 Then
        Dim base As Long: base = 2 + 2 * NR
        Dim m As Long
        For m = 1 To NC
            Dim idxRp As Long, idxCp As Long
            idxRp = base + 2 * m - 1
            idxCp = idxRp + 1

            If x(idxRp) > RP_MAX Then x(idxRp) = RP_MAX
            If x(idxCp) > CP_MAX Then x(idxCp) = CP_MAX
        Next m
    End If
End Sub

' ===========================
'   Nelder-Mead simplex optimizer (pure VBA)
' ===========================
Private Function NelderMead(ByRef x0() As Double, ByVal maxIter As Long, ByVal tolF As Double, ByVal tolX As Double) As Double()
    Dim n As Long, i As Long, j As Long, iter As Long
    Dim alpha As Double, gamma As Double, rho As Double, sigma As Double
    Dim simplex() As Double, fval() As Double
    Dim xc() As Double, xr() As Double, xe() As Double, xk() As Double
    Dim best As Long, worst As Long, secondWorst As Long
    Dim fBest As Double, fWorst As Double, fSecond As Double
    Dim stepRel As Double, stepAbs As Double
    Dim diffF As Double, maxDX As Double

    alpha = 1#: gamma = 2#: rho = 0.5: sigma = 0.5

    n = UBound(x0)
    ReDim simplex(1 To n + 1, 1 To n)
    ReDim fval(1 To n + 1)

    stepRel = 0.1
    stepAbs = 0.000000000001

    For j = 1 To n
        simplex(1, j) = x0(j)
    Next j

    For i = 2 To n + 1
        For j = 1 To n
            simplex(i, j) = x0(j)
        Next j
        If Abs(x0(i - 1)) > 0# Then
            simplex(i, i - 1) = x0(i - 1) * (1# + stepRel)
        Else
            simplex(i, i - 1) = stepAbs
        End If
    Next i

    For i = 1 To n + 1
        ReDim xk(1 To n)
        For j = 1 To n: xk(j) = simplex(i, j): Next j
        fval(i) = ObjSSR(xk)
    Next i

    ReDim xc(1 To n)
    ReDim xr(1 To n)
    ReDim xe(1 To n)

    For iter = 1 To maxIter

        best = 1: worst = 1
        For i = 2 To n + 1
            If fval(i) < fval(best) Then best = i
            If fval(i) > fval(worst) Then worst = i
        Next i

        secondWorst = best
        For i = 1 To n + 1
            If i <> worst Then
                If secondWorst = best Then
                    secondWorst = i
                ElseIf fval(i) > fval(secondWorst) Then
                    secondWorst = i
                End If
            End If
        Next i

        fBest = fval(best): fWorst = fval(worst): fSecond = fval(secondWorst)

        diffF = 0#
        For i = 1 To n + 1
            diffF = Application.Max(diffF, Abs(fval(i) - fBest))
        Next i

        maxDX = 0#
        For j = 1 To n
            maxDX = Application.Max(maxDX, Abs(simplex(worst, j) - simplex(best, j)))
        Next j

        If diffF < tolF And maxDX < tolX Then Exit For

        For j = 1 To n
            xc(j) = 0#
            For i = 1 To n + 1
                If i <> worst Then xc(j) = xc(j) + simplex(i, j)
            Next i
            xc(j) = xc(j) / n
        Next j

        For j = 1 To n
            xr(j) = xc(j) + alpha * (xc(j) - simplex(worst, j))
        Next j
        Dim fr As Double: fr = ObjSSR(xr)

        If fr < fBest Then
            For j = 1 To n
                xe(j) = xc(j) + gamma * (xr(j) - xc(j))
            Next j
            Dim fe As Double: fe = ObjSSR(xe)
            If fe < fr Then
                For j = 1 To n: simplex(worst, j) = xe(j): Next j
                fval(worst) = fe
            Else
                For j = 1 To n: simplex(worst, j) = xr(j): Next j
                fval(worst) = fr
            End If

        ElseIf fr < fSecond Then
            For j = 1 To n: simplex(worst, j) = xr(j): Next j
            fval(worst) = fr

        Else
            Dim xcon() As Double
            ReDim xcon(1 To n)

            If fr < fWorst Then
                For j = 1 To n
                    xcon(j) = xc(j) + rho * (xr(j) - xc(j))
                Next j
            Else
                For j = 1 To n
                    xcon(j) = xc(j) + rho * (simplex(worst, j) - xc(j))
                Next j
            End If

            Dim fcon As Double: fcon = ObjSSR(xcon)

            If fcon < fWorst Then
                For j = 1 To n: simplex(worst, j) = xcon(j): Next j
                fval(worst) = fcon
            Else
                For i = 1 To n + 1
                    If i <> best Then
                        For j = 1 To n
                            simplex(i, j) = simplex(best, j) + sigma * (simplex(i, j) - simplex(best, j))
                        Next j
                        ReDim xk(1 To n)
                        For j = 1 To n: xk(j) = simplex(i, j): Next j
                        fval(i) = ObjSSR(xk)
                    End If
                Next i
            End If
        End If

    Next iter

    best = 1
    For i = 2 To n + 1
        If fval(i) < fval(best) Then best = i
    Next i

    Dim xBest() As Double
    ReDim xBest(1 To n)
    For j = 1 To n
        xBest(j) = simplex(best, j)
        If xBest(j) < 0# Then xBest(j) = 0#
    Next j
    NelderMead = xBest
End Function

' ===========================
'   Stats helpers
' ===========================
Private Sub QuickSort(ByRef a() As Double, ByVal lo As Long, ByVal hi As Long)
    Dim i As Long, j As Long
    Dim pivot As Double, tmp As Double
    i = lo: j = hi
    pivot = a((lo + hi) \ 2)
    Do While i <= j
        Do While a(i) < pivot: i = i + 1: Loop
        Do While a(j) > pivot: j = j - 1: Loop
        If i <= j Then
            tmp = a(i): a(i) = a(j): a(j) = tmp
            i = i + 1: j = j - 1
        End If
    Loop
    If lo < j Then QuickSort a, lo, j
    If i < hi Then QuickSort a, i, hi
End Sub

Private Function Percentile(ByRef a() As Double, ByVal p As Double) As Double
    Dim b() As Double, n As Long, i As Long
    n = UBound(a)
    ReDim b(1 To n)
    For i = 1 To n: b(i) = a(i): Next i
    QuickSort b, 1, n
    If n = 1 Then Percentile = b(1): Exit Function

    Dim k As Double: k = 1 + p * (n - 1)
    Dim k0 As Long: k0 = Int(k)
    Dim d As Double: d = k - k0

    If k0 < 1 Then k0 = 1
    If k0 >= n Then
        Percentile = b(n)
    Else
        Percentile = b(k0) * (1 - d) + b(k0 + 1) * d
    End If
End Function

Private Function Median(ByRef a() As Double) As Double
    Median = Percentile(a, 0.5)
End Function

Private Function LogSpace(ByVal a As Double, ByVal b As Double, ByVal n As Long) As Double()
    Dim out() As Double, i As Long
    ReDim out(1 To n)
    If n = 1 Then
        out(1) = 10 ^ a
    Else
        For i = 1 To n
            out(i) = 10 ^ (a + (b - a) * (i - 1) / (n - 1))
        Next i
    End If
    LogSpace = out
End Function

Private Function Median3(ByVal a As Double, ByVal b As Double, ByVal c As Double) As Double
    ' median of three values
    If a > b Then SwapD a, b
    If b > c Then SwapD b, c
    If a > b Then SwapD a, b
    Median3 = b
End Function

Private Sub SwapD(ByRef a As Double, ByRef b As Double)
    Dim t As Double: t = a: a = b: b = t
End Sub

' ===========================
'   Phase unwrap & SRF estimate (for NC init)
' ===========================
Private Function UnwrapPhase(ByRef phi() As Double) As Double()
    Dim i As Long, n As Long
    n = UBound(phi)
    Dim out() As Double: ReDim out(1 To n)
    out(1) = phi(1)
    Dim offset As Double: offset = 0#
    For i = 2 To n
        Dim d As Double: d = phi(i) - phi(i - 1)
        If d > WorksheetFunction.Pi() Then
            offset = offset - 2# * WorksheetFunction.Pi()
        ElseIf d < -WorksheetFunction.Pi() Then
            offset = offset + 2# * WorksheetFunction.Pi()
        End If
        out(i) = phi(i) + offset
    Next i
    UnwrapPhase = out
End Function

Private Function Estimate_f_srf(ByRef Zre() As Double, ByRef Zim() As Double, ByRef f() As Double) As Double
    ' MATLAB logic:
    ' (1) min |Z|
    ' (2) min phase(unwrap)
    ' (3) max |dphi/dlogf|
    Dim n As Long: n = UBound(f)
    Dim i As Long

    Dim absZ() As Double: ReDim absZ(1 To n)
    Dim phi() As Double: ReDim phi(1 To n)
    Dim lf() As Double: ReDim lf(1 To n)

    For i = 1 To n
        absZ(i) = Sqr(Zre(i) * Zre(i) + Zim(i) * Zim(i))
        phi(i) = WorksheetFunction.Atan2(Zim(i), Zre(i))
        lf(i) = Log(f(i)) / Log(10#)
    Next i

    Dim phiU() As Double
    phiU = UnwrapPhase(phi)

    Dim iZ As Long: iZ = 1
    For i = 2 To n
        If absZ(i) < absZ(iZ) Then iZ = i
    Next i
    Dim fZ As Double: fZ = f(iZ)

    Dim ip As Long: ip = 1
    For i = 2 To n
        If phiU(i) < phiU(ip) Then ip = i
    Next i
    Dim fp As Double: fp = f(ip)

    Dim id As Long: id = 1
    Dim best As Double: best = -1#
    For i = 1 To n - 1
        Dim dphi As Double
        Dim dlf As Double
        dlf = lf(i + 1) - lf(i)
        If Abs(dlf) < 0.000000000001 Then GoTo nxt
        dphi = (phiU(i + 1) - phiU(i)) / dlf
        If Abs(dphi) > best Then
            best = Abs(dphi)
            id = i + 1
        End If
nxt:
    Next i
    Dim fd As Double: fd = f(id)

    Dim f_srf As Double
    f_srf = Median3(fZ, fp, fd)
    If f_srf < 10# Then f_srf = 10#
    Estimate_f_srf = f_srf
End Function

' ===========================
'   Data handling: read, filter, sort
' ===========================
Private Sub SortTripletByF(ByRef f() As Double, ByRef Ls() As Double, ByRef Rs() As Double)
    Dim idx() As Long, i As Long, n As Long
    n = UBound(f)
    ReDim idx(1 To n)
    For i = 1 To n: idx(i) = i: Next i

    QuickSortIndexByF f, idx, 1, n

    Dim f2() As Double, L2() As Double, R2() As Double
    ReDim f2(1 To n): ReDim L2(1 To n): ReDim R2(1 To n)
    For i = 1 To n
        f2(i) = f(idx(i))
        L2(i) = Ls(idx(i))
        R2(i) = Rs(idx(i))
    Next i
    For i = 1 To n
        f(i) = f2(i): Ls(i) = L2(i): Rs(i) = R2(i)
    Next i
End Sub

Private Sub QuickSortIndexByF(ByRef f() As Double, ByRef idx() As Long, ByVal lo As Long, ByVal hi As Long)
    Dim i As Long, j As Long, p As Double
    Dim t As Long
    i = lo: j = hi
    p = f(idx((lo + hi) \ 2))
    Do While i <= j
        Do While f(idx(i)) < p: i = i + 1: Loop
        Do While f(idx(j)) > p: j = j - 1: Loop
        If i <= j Then
            t = idx(i): idx(i) = idx(j): idx(j) = t
            i = i + 1: j = j - 1
        End If
    Loop
    If lo < j Then QuickSortIndexByF f, idx, lo, j
    If i < hi Then QuickSortIndexByF f, idx, i, hi
End Sub

' ===========================
'   Initialization (MATLAB-like)
' ===========================
Private Function InitialGuess(ByVal NR As Long, ByVal NC As Long) As Double()
    Dim i As Long, k As Long

    ' R0 = prctile(real(Zdata),5)
    Dim reZ() As Double: ReDim reZ(1 To gN)
    For i = 1 To gN: reZ(i) = gZre(i): Next i
    Dim R0 As Double: R0 = Percentile(reZ, 0.05)

    ' L0 = median(imag(Zdata)./w)
    Dim Leq() As Double: ReDim Leq(1 To gN)
    For i = 1 To gN
        If gW(i) > 0# Then Leq(i) = gZim(i) / gW(i) Else Leq(i) = 0#
    Next i
    Dim L0 As Double: L0 = Median(Leq)
    If L0 < 0.000000000001 Then L0 = 0.000000000001

    ' w0s = logspace(log10(min(w)*5), log10(max(w)/5), NR)
    Dim wmin As Double: wmin = gW(1)
    Dim wmax As Double: wmax = gW(gN)
    Dim w0s() As Double
    w0s = LogSpace(Log(wmin * 5#) / Log(10#), Log(wmax / 5#) / Log(10#), NR)

    ' Rks = logspace(log10(max(R0*0.3,1e-6)), log10(max(R0*5,5e-6)), NR)
    Dim loR As Double: loR = WorksheetFunction.Max(R0 * 0.3, 0.000001)
    Dim hiR As Double: hiR = WorksheetFunction.Max(R0 * 5#, 0.000005)
    Dim Rks() As Double
    Rks = LogSpace(Log(loR) / Log(10#), Log(hiR) / Log(10#), NR)

    Dim x0() As Double
    ReDim x0(1 To (2 + 2 * NR + 2 * NC))

    x0(1) = R0
    x0(2) = L0

    For k = 1 To NR
        x0(2 + 2 * k - 1) = Rks(k)
        x0(2 + 2 * k) = Rks(k) / w0s(k)
        If x0(2 + 2 * k) < 0.000000000001 Then x0(2 + 2 * k) = 0.000000000001
    Next k

    If NC > 0 Then
        ' SRF estimate like MATLAB
        Dim f_srf As Double
        f_srf = Estimate_f_srf(gZre, gZim, gF)

        Dim Cp_mid As Double
        Cp_mid = 1# / ((2# * WorksheetFunction.Pi() * f_srf) ^ 2 * WorksheetFunction.Max(L0, 0.000000000001))

        Dim spread As Double: spread = 5#
        Dim Cps() As Double
        Cps = LogSpace(Log(WorksheetFunction.Max(Cp_mid / spread, 0.0000000000001)) / Log(10#), _
                       Log(WorksheetFunction.Min(Cp_mid * spread, 0.000001)) / Log(10#), NC)

        Dim base As Long: base = 2 + 2 * NR
        For i = 1 To NC
            x0(base + 2 * i - 1) = 1000000# ' Rp
            x0(base + 2 * i) = Cps(i)       ' Cp
        Next i
    End If

    InitialGuess = x0
End Function

' ===========================
'   Fit main
' ===========================
Public Sub FitFosterRL()
        Dim FMIN_REQ As Double
        Dim FMAX_REQ As Double
        Dim PARALLEL_CAPS_ENABLE As Boolean
        Dim lastRow As Long

    With ActiveSheet

        FMIN_REQ = .Cells(4, 19).Value#
        FMAX_REQ = .Cells(5, 19).Value
        PARALLEL_CAPS_ENABLE = .Cells(6, 19).Value
        lastRow = .Cells(.Rows.Count, "C").End(xlUp).row
        
        If lastRow < 2 Then
            MsgBox "Pas assez de données sur Feuil1 (>=2 lignes).", vbExclamation
            Exit Sub
        End If
    
        ' Read & filter
        Dim f() As Double, Ls() As Double, Rs() As Double
        Dim i As Long, nRaw As Long
        nRaw = lastRow - 1
        ReDim f(1 To nRaw)
        ReDim Ls(1 To nRaw)
        ReDim Rs(1 To nRaw)
    
        Dim nKeep As Long: nKeep = 0
        For i = 11 To lastRow
            Dim fv As Variant, lv As Variant, rv As Variant
            fv = .Cells(i, "C").Value
            lv = .Cells(i, "D").Value
            rv = .Cells(i, "E").Value
            If IsNumeric(fv) And IsNumeric(lv) And IsNumeric(rv) Then
                If CDbl(fv) > 0# And CDbl(lv) > 0# And CDbl(rv) >= 0# Then
                    If CDbl(fv) >= FMIN_REQ And CDbl(fv) <= FMAX_REQ Then
                        nKeep = nKeep + 1
                        f(nKeep) = CDbl(fv)
                        Ls(nKeep) = CDbl(lv)
                        Rs(nKeep) = CDbl(rv)
                    End If
                End If
            End If
        Next i
    
        If nKeep < 8 Then
            MsgBox "Trop peu de points valides dans la bande (n<8).", vbExclamation
            Exit Sub
        End If
    
        ReDim Preserve f(1 To nKeep)
        ReDim Preserve Ls(1 To nKeep)
        ReDim Preserve Rs(1 To nKeep)
    
        SortTripletByF f, Ls, Rs
    
        ' Build globals
        gN = nKeep
        ReDim gW(1 To gN)
        ReDim gF(1 To gN)
        ReDim gZre(1 To gN)
        ReDim gZim(1 To gN)
    
        For i = 1 To gN
            gF(i) = f(i)
            gW(i) = 2# * WorksheetFunction.Pi() * f(i)
            gZre(i) = Rs(i)
            gZim(i) = gW(i) * Ls(i)
        Next i
    
        ' Search NR/NC using AIC (as MATLAB)
        Dim bestAIC As Double: bestAIC = 1E+99
        Dim bestNR As Long, bestNC As Long
        Dim bestX() As Double
        Dim bestRelErr As Double
    
        Dim NC_lo As Long, NC_hi As Long
        If PARALLEL_CAPS_ENABLE Then
            NC_lo = NC_MIN: NC_hi = NC_MAX
        Else
            NC_lo = 0: NC_hi = 0
        End If
    
        Dim NR As Long, NC As Long
        For NR = NR_MIN To NR_MAX
            For NC = NC_lo To NC_hi
                gNR = NR: gNC = NC
    
                Dim x0() As Double
                x0 = InitialGuess(NR, NC)
    
                Dim xFit() As Double
                xFit = NelderMead(x0, 6000, 0.0000000001, 0.000000000001)
                ClampParams xFit, NR, NC
    
                ' RSS and AIC
                Dim rss As Double: rss = ComputeRSS(xFit, NR, NC)
                Dim nObs As Double: nObs = 2# * gN
                Dim kPar As Double: kPar = UBound(xFit)
                Dim AIC As Double: AIC = nObs * Log(rss / nObs) + 2# * kPar
    
                Dim relErr As Double: relErr = ComputeMeanRelErr(xFit, NR, NC)
    
                If AIC < bestAIC Then
                    bestAIC = AIC
                    bestNR = NR
                    bestNC = NC
                    bestX = xFit
                    bestRelErr = relErr
                End If
            Next NC
        Next NR
    
        WriteResults bestNR, bestNC, bestX, bestRelErr
    
        MsgBox "Fit terminé." & vbCrLf & _
               "Meilleur modèle: NR=" & bestNR & ", NC=" & bestNC & vbCrLf & _
               "Erreur relative moyenne ˜ " & Format(100# * bestRelErr, "0.000") & " %", vbInformation
    End With
    
End Sub

Private Function ComputeRSS(ByRef x() As Double, ByVal NR As Long, ByVal NC As Long) As Double
    Dim i As Long
    Dim zmod As Complex, zdat As Complex, dz As Complex
    Dim rss As Double: rss = 0#
    For i = 1 To gN
        zmod = ZFosterTotal_RL_RpCp(gW(i), x, NR, NC)
        zdat = Cx(gZre(i), gZim(i))
        dz = CSub(zmod, zdat)
        rss = rss + (dz.re * dz.re + dz.im * dz.im)
    Next i
    ComputeRSS = rss
End Function

Private Function ComputeMeanRelErr(ByRef x() As Double, ByVal NR As Long, ByVal NC As Long) As Double
    Dim i As Long
    Dim zmod As Complex, zdat As Complex, dz As Complex
    Dim sc As Double, acc As Double
    acc = 0#
    For i = 1 To gN
        zmod = ZFosterTotal_RL_RpCp(gW(i), x, NR, NC)
        zdat = Cx(gZre(i), gZim(i))
        dz = CSub(zmod, zdat)
        sc = CAbs(zdat)
        If sc < 0.000001 Then sc = 0.000001
        acc = acc + (CAbs(dz) / sc)
    Next i
    ComputeMeanRelErr = acc / gN
End Function

Private Sub WriteResults(ByVal NR As Long, ByVal NC As Long, ByRef x() As Double, ByVal relErr As Double)

    Dim wsR As Worksheet
    On Error Resume Next
    Set wsR = ThisWorkbook.Worksheets("Foster_Result")
    On Error GoTo 0
    If wsR Is Nothing Then
        Set wsR = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
        wsR.Name = "Foster_Result"
    Else
        wsR.Cells.Clear
    End If

    wsR.Range("A1").Value = "Meilleur modèle Foster (RL + option Rp/Cp en //)"
    wsR.Range("A2").Value = "NR": wsR.Range("B2").Value = NR
    wsR.Range("A3").Value = "NC": wsR.Range("B3").Value = NC
    wsR.Range("A4").Value = "Erreur relative moyenne": wsR.Range("B4").Value = relErr

    wsR.Range("A6").Value = "Paramètre"
    wsR.Range("B6").Value = "Valeur"

    wsR.Range("A7").Value = "R0 (Ohm)": wsR.Range("B7").Value = x(1)
    wsR.Range("A8").Value = "L0 (H)": wsR.Range("B8").Value = x(2)

    Dim row As Long: row = 10
    Dim k As Long
    For k = 1 To NR
        wsR.Cells(row, 1).Value = "R" & k & " (Ohm)"
        wsR.Cells(row, 2).Value = x(2 + 2 * k - 1)
        wsR.Cells(row + 1, 1).Value = "L" & k & " (H)"
        wsR.Cells(row + 1, 2).Value = x(2 + 2 * k)
        row = row + 3
    Next k

    If NC > 0 Then
        Dim base As Long: base = 2 + 2 * NR
        Dim m As Long
        For m = 1 To NC
            wsR.Cells(row, 1).Value = "Rp" & m & " (Ohm)"
            wsR.Cells(row, 2).Value = x(base + 2 * m - 1)
            wsR.Cells(row + 1, 1).Value = "Cp" & m & " (F)"
            wsR.Cells(row + 1, 2).Value = x(base + 2 * m)
            row = row + 3
        Next m
    End If

    ' Dump modeled vs measured
    wsR.Range("D6").Value = "f(Hz)"
    wsR.Range("E6").Value = "Rs_mes"
    wsR.Range("F6").Value = "Leq_mes(H)"
    wsR.Range("G6").Value = "Rs_mod"
    wsR.Range("H6").Value = "Leq_mod(H)"
    wsR.Range("I6").Value = "|Z|_mes"
    wsR.Range("J6").Value = "|Z|_mod"
    wsR.Range("K6").Value = "phase_mes(deg)"
    wsR.Range("L6").Value = "phase_mod(deg)"

    Dim i As Long, w As Double
    For i = 1 To gN
        w = gW(i)
        wsR.Cells(6 + i, "D").Value = gF(i)
        wsR.Cells(6 + i, "E").Value = gZre(i)
        wsR.Cells(6 + i, "F").Value = gZim(i) / w

        Dim zm As Complex, zdat As Complex
        zm = ZFosterTotal_RL_RpCp(w, x, NR, NC)
        zdat = Cx(gZre(i), gZim(i))

        wsR.Cells(6 + i, "G").Value = zm.re
        wsR.Cells(6 + i, "H").Value = zm.im / w
        wsR.Cells(6 + i, "I").Value = CAbs(zdat)
        wsR.Cells(6 + i, "J").Value = CAbs(zm)
        wsR.Cells(6 + i, "K").Value = CAngle(zdat) * 180# / WorksheetFunction.Pi()
        wsR.Cells(6 + i, "L").Value = CAngle(zm) * 180# / WorksheetFunction.Pi()
    Next i

    wsR.Columns("A:L").AutoFit
End Sub



