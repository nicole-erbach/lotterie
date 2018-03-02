import requests
import json
import sqlite3
import datetime


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
    euro1 INTEGER,
    euro2 INTEGER)
    """
    cursor.execute(sql_command)


def getDrawdays(year):

    # get and decode drawdays from lotto.de
    url = "https://www.lotto.de/bin/ej_archiv?year=" + str(year)
    response = requests.get(url)
    responseDecoded = json.loads(response.text)    
    drawdays = [item["date"] for item in responseDecoded[str(year)]]
    drawdays.sort()
     
    return drawdays
    
    
def getDataAndSaveToDatabase(drawday, connection):

    cursor = connection.cursor()    

    # get and decode data from lotto.de
    url = "https://www.lotto.de/bin/ej_archiv?drawday=" + drawday
    response = requests.get(url)
    responseDecoded = json.loads(response.text)

    # table numbers: extract data and insert
    numbers = [int(number) for number in responseDecoded[drawday]["ej"]["gewinnzahlen"]]
    euro = [int(number) for number in responseDecoded[drawday]["ej"]["zwei_aus_acht"]]
    try:
        stake = int(float(responseDecoded[drawday]["ej"]["spieleinsatz"]))
    except TypeError:
        # drawn numbers available while quotas are not
        return    


    sql_command = """INSERT INTO numbers(date, stake, no1, no2, no3, no4, no5, euro1, euro2) VALUES(?,?,?,?,?,?,?,?,?)"""
    toInsert = [drawday] + [stake] + numbers + euro
    cursor.execute(sql_command, toInsert)
    connection.commit()
    

    # table quotas: extract and insert data
    numbersId = cursor.execute("SELECT last_insert_rowid()").fetchone()[0]

    quotaList = responseDecoded[drawday]["ej"]["quoten"]

    sql_command = """INSERT INTO quotas(numbersId, description, noWinners, amount) VALUES(?,?,?,?)"""
    for quota in quotaList:

        description = quota["beschreibung"]
        amount = int(float(quota["quote"]))
        noWinners = int(quota["anzahl"])
        toInsert = [numbersId] + [description] + [amount] + [noWinners]
        cursor.execute(sql_command, [numbersId] + [description] + [noWinners] + [amount]) 
    connection.commit()



def main():
    
    # establilsh connection
    connection = sqlite3.connect("euroJackpot.db")
    cursor = connection.cursor()
    
    # get last drawday or create database
    try:
        dbLastDrawday = cursor.execute("SELECT MAX(date) FROM numbers").fetchone()[0]
        if dbLastDrawday == None:
            dbLastDrawday = "2012-04-20"
    except sqlite3.OperationalError:
        
        print("create Database")
        createDatabase(cursor)
        dbLastDrawday = "2012-04-20"
    
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
    

if __name__ == "__main__": main()
