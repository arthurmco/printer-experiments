import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("127.0.0.1", 9100))
    s.listen()
    print("listening to 0.0.0.0:9100")

    conn, addr = s.accept()
    with conn:
        print("job accepted!")
        count = 1
        
        with open("out.epson", "wb") as out:    
            while count > 0:
                msg = conn.recv(10240)

                print("Receiving message")
                
                count = len(msg)
                out.write(msg)

            print("Received everything.")
        
