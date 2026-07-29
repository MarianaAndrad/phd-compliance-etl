db = db.getSiblingDB('admin');
db.auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD);

// Create application database
db = db.getSiblingDB(process.env.DB_MONGO_NAME);

// Create user for application database
db.createUser({
  user: process.env.DB_MONGO_USERNAME,
  pwd: process.env.DB_MONGO_PASSWORD,
  roles: [
    {
      role: 'readWrite',
      db: process.env.DB_MONGO_NAME
    }
  ]
});

// Create an initial collection to ensure database is created
db.createCollection(process.env.DB_MONGO_CATALOG_COLLECTION)
db.createCollection(process.env.DB_MONGO_CONTROL_COLLECTION)