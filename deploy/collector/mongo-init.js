const database = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE || "moodle-statistics");
database.users.updateOne(
  {email: process.env.COLLECTOR_ADMIN_EMAIL},
  {$setOnInsert: {
    name: "Collector", surname: "Administrator", lastname: "Local",
    email: process.env.COLLECTOR_ADMIN_EMAIL,
    password: process.env.COLLECTOR_ADMIN_PASSWORD, position: "admin"
  }}, {upsert: true}
);
database.users.createIndex({email: 1}, {unique: true});
database.statistics.createIndex({student_id: 1});
database.statistics.createIndex({"actions.timestamp": 1});
database.statistics.createIndex({session_id: 1});
