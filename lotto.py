import requests
import json
import sqlite3
import datetime
import pandas as pd
import numpy as np

# function to create database
def createDatabase(cursor):
   
    # command to create table gewinner
    sql_command = """
    CREATE TABLE IF NOT EXISTS quotas (
    id INTEGER PRIMARY KEY,
    numbersId INTEGER,
    description STRING,
    noWinners INTEGER,
    amount INTEGER)
    """
    cursor.execute(sql_command)

    # command to create table lottozahlen
    sql_command = """
    CREATE TABLE IF NOT EXISTS numbers (
    id INTEGER PRIMARY KEY,
    date STRING,
    stake INTEGER,
    no1 INTEGER,
    no2 INTEGER,
    no3 INTEGER,
    no4 INTEGER,
    no5 INTEGER,
    no6 INTEGER,
    sz INTEGER,
    zz INTEGER)
    """
    cursor.execute(sql_command)


def getDrawdays(year):

    # get and decode drawdays from lotto.de
    url = "https://www.lotto.de/bin/6aus49_archiv?year=" + str(year)
    response = requests.get(url)
    responseDecoded = json.loads(response.text)    
    drawdays = [item["date"] for item in responseDecoded[str(year)]]
    drawdays.sort()
     
    return drawdays
    
    
def getDataAndSaveToDatabase(drawday, connection):

    cursor = connection.cursor()

    # get and decode data from lotto.de
    url = "https://www.lotto.de/bin/6aus49_archiv?drawday=" + drawday
    response = requests.get(url)
    responseDecoded = json.loads(response.text)

    # table numbers: extract data and insert
    numbers = [int(number) for number in responseDecoded[drawday]["lotto"]["gewinnzahlen"]]
    try:
        stake = int(float(responseDecoded[drawday]["lotto"]["spieleinsatz"]))
    except TypeError:
        # two cases: irregular entry for 2013-03-02 and
        # drawn numbers already already available while quotas are not
        return

    try:
        sz = int(responseDecoded[drawday]["lotto"]["superzahl"])
    except TypeError:
        sz = -1 

    try:
        zz = int(responseDecoded[drawday]["lotto"]["zusatzzahl"])
    except TypeError:
        zz = -1 
    
    sql_command = """INSERT INTO numbers(date, stake, no1, no2, no3, no4, no5, no6, sz, zz) VALUES(?,?,?,?,?,?,?,?,?,?)"""
    toInsert = [drawday] + [stake] + numbers + [sz] + [zz]
    cursor.execute(sql_command, toInsert)
    connection.commit()
    

    # table quotas: extract and insert data
    numbersId = cursor.execute("SELECT last_insert_rowid()").fetchone()[0]

    quotaList = responseDecoded[drawday]["lotto"]["quoten"]

    sql_command = """INSERT INTO quotas(numbersId, description, noWinners, amount) VALUES(?,?,?,?)"""
    for quota in quotaList:

        description = quota["beschreibung"]
        amount = int(float(quota["quote"]))
        noWinners = int(quota["anzahl"])
        toInsert = [numbersId] + [description] + [amount] + [noWinners]
        cursor.execute(sql_command, [numbersId] + [description] + [noWinners] + [amount]) 
    connection.commit()



def updateDatabase():
 
   # establilsh connection
    connection = sqlite3.connect("lottozahlen.db")
    cursor = connection.cursor()
    
    # get last drawday or create database
    try:
        dbLastDrawday = cursor.execute("SELECT MAX(date) FROM numbers").fetchone()[0]
        if dbLastDrawday == None:
            dbLastDrawday = "2002-01-02"
    except sqlite3.OperationalError:
        
        print("create Database")
        createDatabase(cursor)
        dbLastDrawday = "2002-01-02"
    
    # get lottodata from these years
    yearsToCheck = range(int(dbLastDrawday[:4]), datetime.datetime.today().year + 1)
    
    for year in yearsToCheck:
    
        drawdayList = getDrawdays(year)
        
        # remove drawdays already in database
        if year == yearsToCheck[0]:
            drawdayList = [drawday for drawday in drawdayList if drawday > dbLastDrawday] 
    
        for drawday in drawdayList:
            print(drawday)
            getDataAndSaveToDatabase(drawday, connection)

    cursor.close()
    connection.close()
    print("database updated")

def prepareNumbersAnalysis():
    
    # probabilities used below:
    # prob6Correct = 1 / 13983816
    # probMin5Correct = 259 / 13983816
    # probMin4Correct = 13804 / 13983816
    # probMin3Correct = 260624 / 13983816
    
    # analyse 3 categories, corresponding probabilities for success in each of these categories hardcoded below.
    # e.g. "3 Richtige": having 3 correct numbers OR MORE,
    categoriesToAnalyse = ["5 Richtige", "4 Richtige", "3 Richtige"]
    probabilityList = [259/13983816, 13804/13983816, 260624/13983816]
    
    # connect to database
    connection = sqlite3.connect("lottozahlen.db")
   
    # get id of first draw with new rules (price change from 0.75€ to 1€, Zusatzzahl removed, classes changed) 
    cursor = connection.cursor()
    sqlCommand = """SELECT id FROM numbers WHERE date >= "2013-05-04" limit 1"""
    ruleChangeId = cursor.execute(sqlCommand).fetchone()[0]
    cursor.close()
    
    # prepare dataframes:
    # draws in rows 
    # dummy variables for each number
    sqlCommand = "SELECT date, no1, no2, no3, no4, no5, no6 FROM numbers"
    df = pd.read_sql_query(sqlCommand, connection)
    
    dummyNumbers = pd.concat([pd.get_dummies(df["no1"]), pd.get_dummies(df["no2"]), pd.get_dummies(df["no3"]), pd.get_dummies(df["no4"]), pd.get_dummies(df["no5"]), pd.get_dummies(df["no6"])], axis=1)
    dummyNumbers = dummyNumbers.groupby(dummyNumbers.columns, axis=1).sum()
    
    # create singlevalue "unpopularity" (reciprocal value of popularity) measure for each draw and each category:
    # unpopularity = (expected number of winners) / (number of winners)
    # with (expected number of winners) = categoryProbability * (number of participants)
    # and (number of participants) = stake / (cost per bet) 
    unpopularityNumbers = pd.DataFrame()
    sqlCommand = """SELECT numbersId, SUM(noWinners), stake FROM quotas LEFT JOIN numbers ON numbers.id = quotas.numbersId WHERE SUBSTR(description,1,10) = ? GROUP BY numbersId"""
    
    for index, category in enumerate(categoriesToAnalyse):
    
        columnName = category + " ratio"
        
        # database request
        raw = pd.read_sql_query(sqlCommand, connection, params=(category,))
        
        # calculate unpopularity value
        unpopularityNumbers[columnName] = ((raw["stake"]) * probabilityList[index]) / raw["SUM(noWinners)"]
        
        # correct underestimation due to rulechange (#participants = stake / 0.75 before rulechange)
        unpopularityNumbers[columnName][raw["numbersId"] < ruleChangeId] /= 0.75
   
    cursor.close() 
    connection.close()
    
    return dummyNumbers, unpopularityNumbers

def getNumbersImpact(normalize=True):

    # naive numbers mean-analysis, single value for numbers impact:
    # (mean winning amount with sz != n) / (mean winning amount with sz == n)
    
    numbers, unpopularityNumbers = prepareNumbersAnalysis()
    numbers = numbers.values
    unpopularityNumbers = unpopularityNumbers.values
    
    numbersImpact = np.zeros([49])
    for i in range(49):
        numbersImpact[i] = unpopularityNumbers[numbers[:,i] == 1].mean() / unpopularityNumbers[numbers[:,i] != 1].mean() -1
    
    if normalize:
        numbersImpact -= numbersImpact.min()
        numbersImpact /= numbersImpact.max()    
    
    return numbersImpact

def prepareSzAnalysis():
    
    # probabilities used below:
    # probMin2Correct = 2111774 / 13983816
    # probSzCorrect = 1/10
    
    # probability to succeed in any winning class with correct Superzahl (with at least 2 correct numbers)
    probability = [2111774 / 13983816 * 1 / 10]
    
    # connect to database
    connection = sqlite3.connect("lottozahlen.db")
  
    # get all drawn superzahl 
    sqlCommand = """SELECT sz FROM numbers WHERE date >= "2013-05-04" """
    sz = pd.read_sql_query(sqlCommand, connection)

    # get unpopularity value (see prepareNumbersAnalysis)
    unpopularitySz = pd.DataFrame()
    sqlCommand = """SELECT SUM(noWinners), stake FROM quotas LEFT JOIN numbers ON numbers.id = quotas.numbersId WHERE (SUBSTR(description, 12, 4) = "+ SZ" AND date >= "2013-05-04") GROUP BY numbersId"""
    raw = pd.read_sql_query(sqlCommand, connection)
    unpopularitySz["SZ"] = raw["stake"] * probability / raw["SUM(noWinners)"]

    connection.close()

    return sz, unpopularitySz

def getSzImpact(normalize=True):

    # single value for numbers impact:
    # (mean winning amount with sz != n) / (mean winning amount with sz == n)
    
    sz, unpopularitySz = prepareSzAnalysis()
    sz = sz.values
    unpopularitySz = unpopularitySz.values
    
    szImpact = np.zeros([10])
    for i in range(10):
        szImpact[i] = unpopularitySz[sz==i].mean() / unpopularitySz[sz!=i].mean() -1

    if normalize:
        szImpact -= szImpact.min()
        szImpact /= szImpact.max()    
    
    return szImpact 

    
def pick6(listOfNumbers):
    
    if len(listOfNumbers) > 13:
        print("Too many numbers leading to too many combinations. Please limit the amount to max 13 numbers")
        return

    from sklearn.ensemble import RandomForestRegressor
    import itertools
    
    # prepare random forest regressor
    forestNumbers = RandomForestRegressor(n_estimators=550, max_depth=50, n_jobs=4)

    # get lottodata in prepared pandas dataframes (dummy variables)
    numbers, unpopularity = prepareNumbersAnalysis()

    # train forest
    forestNumbers.fit(numbers.values, unpopularity.values)

    combinations = itertools.combinations(listOfNumbers,6)
    best5 = 0
    best4 = 0
    best3 = 0
    bestCombination5 = listOfNumbers[:6]
    bestCombination4 = listOfNumbers[:6]
    bestCombination3 = listOfNumbers[:6]
    selectionDummy = np.zeros(49)
    for selection in combinations:
        selectionDummy.fill(0)
        for i in selection:
            selectionDummy[i] = 1
        prediction = forestNumbers.predict(selectionDummy.reshape(1,-1))[0]
        if prediction[2] > best3:
            best3 = prediction[2]
            bestCombination3 = selection
        if prediction[1] > best4:
            best4 = prediction[1]
            bestCombination4 = selection
        if prediction[0] > best5:
            best5 = prediction[0]
            bestCombination5 = selection

    return(np.sort(bestCombination3), np.sort(bestCombination4), np.sort(bestCombination5))

def main():

    updateDatabase()


if __name__ == "__main__": main()
