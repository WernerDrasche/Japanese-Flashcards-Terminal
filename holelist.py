from collections import UserList

class HoleList(UserList):
    def __init__(self, data=[]):
        self.free = []
        super().__init__(data)
    
    def __delitem__(self, i):
        if isinstance(i, slice):
            raise ValueError("slice indexing not supported")
        self.data[i] = None
        if i == len(self.data) - 1:
            for y in range(i, -1, -1):
                if self.data[y]:
                    del self.data[y+1:]
                    for l in range(len(self.free)):
                        if self.free[l] > y:
                            del self.free[l]
        else:
            self.free.append(i)

    def __len__(self):
        return len(self.data) - len(self.free)

    def __iter__(self):
        def iterator():
            for element in self.data:
                if element:
                    yield element
        return iterator()

    def add(self, element):
        if self.free:
            i = self.free.pop()
            self.data[i] = element
        else:
            i = len(self.data)
            self.data.append(element)
        return i

if __name__ == "__main__":
    x = HoleList()
    x.add(1)
    x.add(2)
    del x[0]
    x.add(3)
    x.add(4)
    del x[1]
    print(x)
    for e in x:
        print(e)
    #del x[2]
    #print(x)